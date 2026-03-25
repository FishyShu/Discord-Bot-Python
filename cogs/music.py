from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils.player import GuildMusicPlayer, LoopMode, TrackInfo, SOURCE_BADGES
from utils.youtube import extract_info, extract_playlist, is_youtube_playlist, search_youtube, get_stream_url, FFMPEG_OPTIONS
from utils.spotify import is_spotify_url, get_tracks_from_url
from utils.tidal import is_tidal_url, get_tracks_from_tidal_url
from utils.audio_filters import AUDIO_FILTERS

import functools

log = logging.getLogger(__name__)

IDLE_TIMEOUT = 300  # 5 minutes
MAX_QUEUE_SIZE = 500


def _build_af(player: GuildMusicPlayer, track: TrackInfo) -> str:
    """Build an FFmpeg -af filter string from active filter and crossfade settings."""
    parts = []
    if player.active_filter and player.active_filter != "none":
        af = AUDIO_FILTERS.get(player.active_filter, "")
        if af:
            parts.append(af)
    if player.crossfade > 0:
        parts.append(f"afade=t=in:st=0:d={player.crossfade}")
        if track.duration:
            fade_out = max(0, int(track.duration) - player.crossfade)
            parts.append(f"afade=t=out:st={fade_out}:d={player.crossfade}")
    return ",".join(parts)


class SearchSelect(discord.ui.Select):
    """Dropdown for /search results."""

    def __init__(self, results: list[dict], cog: Music):
        self.results = results
        self.cog = cog
        options = [
            discord.SelectOption(
                label=r.get("title", "Unknown")[:100],
                description=f"Duration: {int(r.get('duration', 0)) // 60}:{int(r.get('duration', 0)) % 60:02d}" if r.get("duration") else "Unknown duration",
                value=str(i),
            )
            for i, r in enumerate(results)
        ]
        super().__init__(placeholder="Pick a track...", options=options)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        result = self.results[idx]
        url = result.get("webpage_url") or result.get("url") or result.get("original_url", "")
        thumb = result.get("thumbnail")
        if not thumb:
            thumbs = result.get("thumbnails")
            if thumbs:
                thumb = thumbs[-1].get("url") if isinstance(thumbs[-1], dict) else thumbs[-1]
        track = TrackInfo(
            title=result.get("title", "Unknown"),
            url=url,
            duration=result.get("duration"),
            thumbnail=thumb,
            requester=interaction.user.display_name,
            stream_url=None,  # flat search results don't have stream URLs; resolved lazily
            source="search",
        )
        player = await self.cog.get_player(interaction.guild.id)
        if len(player.queue) >= MAX_QUEUE_SIZE:
            await interaction.response.send_message("Queue is full (max 500 tracks).", ephemeral=True)
            return
        player.add(track)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Added to queue",
                description=f"**{track.title}** [{track.duration_str}]",
                color=discord.Color.green(),
            )
        )
        # Start playback if nothing is playing
        vc = interaction.guild.voice_client
        if vc and not vc.is_playing() and not vc.is_paused():
            await self.cog._play_next(interaction.guild)


class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary, emoji="\u274c")

    async def callback(self, interaction: discord.Interaction):
        self.view.stop()
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(description="Search cancelled.", color=discord.Color.light_grey()),
            view=self.view,
        )


class SearchView(discord.ui.View):
    def __init__(self, results: list[dict], cog: Music):
        super().__init__(timeout=60)
        self.add_item(SearchSelect(results, cog))
        self.add_item(CancelButton())

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class NowPlayingView(discord.ui.View):
    """Persistent buttons on the Now Playing embed."""

    def __init__(self, cog: Music, guild: discord.Guild):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild = guild

    def _check_voice(self, interaction: discord.Interaction) -> bool:
        vc = self.guild.voice_client
        if not vc:
            return False
        if not interaction.user.voice or interaction.user.voice.channel != vc.channel:
            return False
        return True

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="\u23f8\ufe0f")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_voice(interaction):
            await interaction.response.send_message("You must be in the voice channel.", ephemeral=True)
            return
        vc = self.guild.voice_client
        if vc.is_paused():
            vc.resume()
            button.label = "Pause"
            button.emoji = "\u23f8\ufe0f"
            await interaction.response.edit_message(view=self)
        elif vc.is_playing():
            vc.pause()
            button.label = "Resume"
            button.emoji = "\u25b6\ufe0f"
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, emoji="\u23ed\ufe0f")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_voice(interaction):
            await interaction.response.send_message("You must be in the voice channel.", ephemeral=True)
            return
        vc = self.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message(
                embed=discord.Embed(description="Skipped.", color=discord.Color.blurple()),
            )
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="\u23f9\ufe0f")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_voice(interaction):
            await interaction.response.send_message("You must be in the voice channel.", ephemeral=True)
            return
        player = await self.cog.get_player(self.guild.id)
        player.clear()
        player.cancel_idle_timer()
        vc = self.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        await interaction.response.send_message(
            embed=discord.Embed(description="Stopped and disconnected.", color=discord.Color.red()),
        )

    @discord.ui.button(label="Loop: Off", style=discord.ButtonStyle.secondary, emoji="\U0001f501")
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._check_voice(interaction):
            await interaction.response.send_message("You must be in the voice channel.", ephemeral=True)
            return
        player = await self.cog.get_player(self.guild.id)
        cycle = [LoopMode.OFF, LoopMode.SINGLE, LoopMode.QUEUE]
        idx = cycle.index(player.loop_mode)
        player.loop_mode = cycle[(idx + 1) % len(cycle)]
        button.label = f"Loop: {player.loop_mode.value.capitalize()}"
        await interaction.response.edit_message(view=self)


class QueueView(discord.ui.View):
    """Paginated queue display."""

    PER_PAGE = 10

    def __init__(self, player: GuildMusicPlayer):
        super().__init__(timeout=120)
        self.player = player
        self.page = 0
        self._update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, -(-len(self.player.queue) // self.PER_PAGE))  # ceil division

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Queue", color=discord.Color.blurple())
        if self.player.current:
            embed.add_field(
                name="Now Playing",
                value=f"**{self.player.current.title}** [{self.player.current.duration_str}]",
                inline=False,
            )
        if self.player.queue:
            start = self.page * self.PER_PAGE
            end = start + self.PER_PAGE
            page_tracks = self.player.queue[start:end]
            lines = [
                f"`{start + i + 1}.` **{t.title}** [{t.duration_str}]"
                for i, t in enumerate(page_tracks)
            ]
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        elif not self.player.current:
            embed.description = "The queue is empty."
        embed.set_footer(
            text=f"Page {self.page + 1}/{self.total_pages} | Loop: {self.player.loop_mode.value} | Volume: {int(self.player.volume * 100)}%"
        )
        return embed

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class HistoryView(discord.ui.View):
    """Paginated track history display."""

    PER_PAGE = 10

    def __init__(self, rows: list[dict]):
        super().__init__(timeout=120)
        self.rows = rows
        self.page = 0
        self._update_buttons()

    @property
    def total_pages(self) -> int:
        return max(1, -(-len(self.rows) // self.PER_PAGE))

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title="Track History", color=discord.Color.blurple())
        start = self.page * self.PER_PAGE
        page_rows = self.rows[start:start + self.PER_PAGE]
        lines = []
        for i, r in enumerate(page_rows):
            badge = SOURCE_BADGES.get(r.get("source") or "", "")
            date = (r.get("played_at") or "")[:16]
            req = r.get("requester") or "unknown"
            lines.append(f"`#{start + i + 1}` {badge} **{r['title']}** — {req} @ {date}")
        embed.description = "\n".join(lines) if lines else "No history."
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages}")
        return embed

    def _update_buttons(self):
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: dict[int, GuildMusicPlayer] = {}

    async def get_player(self, guild_id: int) -> GuildMusicPlayer:
        if guild_id not in self.players:
            from dashboard import db
            gid = str(guild_id)
            vol_str = await db.get_guild_setting(gid, "music_default_volume", "50")
            try:
                vol = int(vol_str)
            except (TypeError, ValueError):
                vol = 50
            player = GuildMusicPlayer()
            player.volume = max(0, min(100, vol)) / 100.0
            self.players[guild_id] = player
        return self.players[guild_id]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        """Ensure the bot is in the user's voice channel. Returns VoiceClient or None."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("You need to be in a voice channel.", ephemeral=True)
            return None

        channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        if vc is None:
            vc = await channel.connect()
        elif vc.channel != channel:
            await vc.move_to(channel)

        return vc

    async def _play_next(self, guild: discord.Guild):
        """Play the next track in the guild's queue."""
        player = await self.get_player(guild.id)
        vc = guild.voice_client
        if vc is None:
            return

        while True:
            track = player.skip()
            if track is None:
                # Nothing left — start idle timer
                player.cancel_idle_timer()

                async def _idle_disconnect():
                    await asyncio.sleep(IDLE_TIMEOUT)
                    if guild.voice_client and not guild.voice_client.is_playing():
                        await guild.voice_client.disconnect()
                        if player.text_channel:
                            await player.text_channel.send(
                                embed=discord.Embed(
                                    description="Disconnected due to inactivity.",
                                    color=discord.Color.orange(),
                                )
                            )

                player.start_idle_timer(_idle_disconnect())
                return

            player.cancel_idle_timer()

            # Lazy-resolve stream URL (skip if already cached from extraction)
            stream_url = track.stream_url or await get_stream_url(track.url)
            if stream_url is None and track.url.startswith("ytsearch:"):
                from dashboard import db
                fallback = await db.get_guild_setting(str(guild.id), "music_fallback_service", "youtube")
                if fallback == "soundcloud":
                    sc_url = track.url.replace("ytsearch:", "scsearch:", 1)
                    stream_url = await get_stream_url(sc_url)
                    if stream_url:
                        track.source = "soundcloud"
            if stream_url is None:
                if player.text_channel:
                    await player.text_channel.send(f"Could not get stream for **{track.title}**, skipping.")
                continue  # try next track instead of recursing

            break  # got a valid stream, proceed to play

        track.stream_url = stream_url

        # Build dynamic FFmpeg options with filters
        af = _build_af(player, track)
        ff_opts = dict(FFMPEG_OPTIONS)
        if af:
            ff_opts["options"] = f'-vn -af "{af}"'
        audio_source = discord.FFmpegPCMAudio(stream_url, **ff_opts)
        audio_source = discord.PCMVolumeTransformer(audio_source, volume=player.volume)

        def after_play(error):
            if error:
                log.error("Playback error: %s", error)
            asyncio.run_coroutine_threadsafe(self._play_next(guild), self.bot.loop)

        vc.play(audio_source, after=after_play)

        # Log to track history (non-blocking)
        from dashboard import db as _db
        asyncio.create_task(_db.add_track_history(
            str(guild.id), track.title, track.url, track.source, track.requester
        ))

        if player.text_channel:
            # Disable buttons on old Now Playing message
            if player.now_playing_message is not None:
                try:
                    await player.now_playing_message.edit(view=None)
                except Exception as e:
                    log.debug("Failed to resolve thumbnail for '%s': %s", track.title, e)
            embed = discord.Embed(
                title="Now Playing",
                description=f"**{track.title}** [{track.duration_str}]",
                color=discord.Color.blurple(),
            )
            if track.thumbnail:
                embed.set_thumbnail(url=track.thumbnail)
            if track.requester:
                embed.set_footer(text=f"Requested by {track.requester}")
            badge = SOURCE_BADGES.get(track.source or "", "")
            embed.add_field(
                name="Source",
                value=f"{badge} {(track.source or 'unknown').capitalize()}",
                inline=True,
            )
            if player.active_filter and player.active_filter != "none":
                embed.add_field(name="Filter", value=player.active_filter.capitalize(), inline=True)
            view = NowPlayingView(self, guild)
            # Update loop button label to reflect current state
            for item in view.children:
                if hasattr(item, 'label') and item.label.startswith("Loop:"):
                    item.label = f"Loop: {player.loop_mode.value.capitalize()}"
            player.now_playing_message = await player.text_channel.send(embed=embed, view=view)

    # ------------------------------------------------------------------
    # Slash Commands
    # ------------------------------------------------------------------

    @app_commands.command(name="play", description="Play a song from YouTube/Spotify URL or search query")
    @app_commands.describe(query="YouTube URL, Spotify URL, or search text")
    async def play(self, interaction: discord.Interaction, query: str):
        vc = await self._ensure_voice(interaction)
        if vc is None:
            return

        await interaction.response.defer()
        player = await self.get_player(interaction.guild.id)
        player.text_channel = interaction.channel

        tracks_added: list[TrackInfo] = []

        is_url = query.startswith("http://") or query.startswith("https://")

        if is_youtube_playlist(query):
            entries = await extract_playlist(query)
            if not entries:
                await interaction.followup.send("Could not load YouTube playlist.", ephemeral=True)
                return
            remaining = MAX_QUEUE_SIZE - len(player.queue)
            for entry in entries[:remaining]:
                vid_url = entry.get("webpage_url") or entry.get("url") or ""
                if not vid_url.startswith("http") and entry.get("id"):
                    vid_url = f"https://www.youtube.com/watch?v={entry['id']}"
                track = TrackInfo(
                    title=entry.get("title", "Unknown"),
                    url=vid_url,
                    duration=entry.get("duration"),
                    thumbnail=entry.get("thumbnail"),
                    requester=interaction.user.display_name,
                    source="youtube",
                )
                player.add(track)
                tracks_added.append(track)
        elif is_spotify_url(query):
            loop = asyncio.get_running_loop()
            spotify_tracks = await loop.run_in_executor(None, functools.partial(get_tracks_from_url, query))
            if not spotify_tracks:
                await interaction.followup.send("Could not get tracks from Spotify URL.", ephemeral=True)
                return
            remaining = MAX_QUEUE_SIZE - len(player.queue)
            if remaining <= 0:
                await interaction.followup.send("Queue is full (max 500 tracks).", ephemeral=True)
                return
            spotify_tracks = spotify_tracks[:remaining]
            for st in spotify_tracks:
                track = TrackInfo(
                    title=st["title"],
                    url=f"ytsearch:{st['query']}",
                    duration=st.get("duration"),
                    requester=interaction.user.display_name,
                    source="spotify",
                )
                player.add(track)
                tracks_added.append(track)
        elif is_tidal_url(query):
            loop = asyncio.get_running_loop()
            tidal_tracks = await loop.run_in_executor(None, functools.partial(get_tracks_from_tidal_url, query))
            if not tidal_tracks:
                await interaction.followup.send("Could not get tracks from Tidal URL.", ephemeral=True)
                return
            remaining = MAX_QUEUE_SIZE - len(player.queue)
            if remaining <= 0:
                await interaction.followup.send("Queue is full (max 500 tracks).", ephemeral=True)
                return
            tidal_tracks = tidal_tracks[:remaining]
            for tt in tidal_tracks:
                track = TrackInfo(
                    title=tt["title"],
                    url=f"ytsearch:{tt['query']}",
                    duration=tt.get("duration"),
                    requester=interaction.user.display_name,
                    source="tidal",
                )
                player.add(track)
                tracks_added.append(track)
        elif not is_url:
            # Search query — show results picker
            results = await search_youtube(query)
            if not results:
                await interaction.followup.send("No results found.", ephemeral=True)
                return
            embed = discord.Embed(title=f"Search results for: {query}", color=discord.Color.blurple())
            for i, r in enumerate(results, 1):
                dur = int(r.get("duration", 0) or 0)
                embed.add_field(
                    name=f"{i}. {r.get('title', 'Unknown')}",
                    value=f"Duration: {dur // 60}:{dur % 60:02d}",
                    inline=False,
                )
            view = SearchView(results, self)
            await interaction.followup.send(embed=embed, view=view)
            return
        else:
            if len(player.queue) >= MAX_QUEUE_SIZE:
                await interaction.followup.send("Queue is full (max 500 tracks).", ephemeral=True)
                return
            info = await extract_info(query)
            if info is None:
                await interaction.followup.send("No results found.", ephemeral=True)
                return
            _track_url = info.get("webpage_url") or info.get("original_url") or query
            _src = "soundcloud" if "soundcloud.com" in query else "youtube"
            track = TrackInfo(
                title=info.get("title", "Unknown"),
                url=_track_url,
                duration=info.get("duration"),
                thumbnail=info.get("thumbnail"),
                requester=interaction.user.display_name,
                stream_url=info.get("url"),
                source=_src,
            )
            player.add(track)
            tracks_added.append(track)

        if len(tracks_added) == 1:
            t = tracks_added[0]
            embed = discord.Embed(
                title="Added to queue",
                description=f"**{t.title}** [{t.duration_str}]",
                color=discord.Color.green(),
            )
        else:
            if is_tidal_url(query):
                source = "Tidal"
            elif is_spotify_url(query):
                source = "Spotify"
            else:
                source = "YouTube playlist"
            embed = discord.Embed(
                title="Added to queue",
                description=f"**{len(tracks_added)} tracks** from {source}",
                color=discord.Color.green(),
            )
        await interaction.followup.send(embed=embed)

        if not vc.is_playing() and not vc.is_paused():
            await self._play_next(interaction.guild)

    @app_commands.command(name="search", description="Search YouTube and pick a result")
    @app_commands.describe(query="Search query")
    async def search(self, interaction: discord.Interaction, query: str):
        vc = await self._ensure_voice(interaction)
        if vc is None:
            return

        await interaction.response.defer()
        player = await self.get_player(interaction.guild.id)
        player.text_channel = interaction.channel

        results = await search_youtube(query)
        if not results:
            await interaction.followup.send("No results found.", ephemeral=True)
            return

        embed = discord.Embed(title=f"Search results for: {query}", color=discord.Color.blurple())
        for i, r in enumerate(results, 1):
            dur = r.get("duration", 0) or 0
            embed.add_field(
                name=f"{i}. {r.get('title', 'Unknown')}",
                value=f"Duration: {dur // 60}:{dur % 60:02d}",
                inline=False,
            )

        view = SearchView(results, self)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="skip", description="Skip the current track")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()  # triggers after callback → _play_next
            await interaction.response.send_message(
                embed=discord.Embed(description="Skipped.", color=discord.Color.blurple())
            )
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message(
                embed=discord.Embed(description="Paused.", color=discord.Color.orange())
            )
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message(
                embed=discord.Embed(description="Resumed.", color=discord.Color.green())
            )
        else:
            await interaction.response.send_message("Nothing is paused.", ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback, clear queue, and disconnect")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        player = await self.get_player(interaction.guild.id)
        player.clear()
        player.cancel_idle_timer()
        if vc:
            vc.stop()
            await vc.disconnect()
        self.players.pop(interaction.guild.id, None)
        await interaction.response.send_message(
            embed=discord.Embed(description="Stopped and disconnected.", color=discord.Color.red())
        )

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue(self, interaction: discord.Interaction):
        player = await self.get_player(interaction.guild.id)
        view = QueueView(player)
        embed = view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="nowplaying", description="Show the currently playing track")
    async def nowplaying(self, interaction: discord.Interaction):
        player = await self.get_player(interaction.guild.id)
        if not player.current:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return
        t = player.current
        embed = discord.Embed(
            title="Now Playing",
            description=f"**{t.title}** [{t.duration_str}]",
            color=discord.Color.blurple(),
        )
        if t.thumbnail:
            embed.set_thumbnail(url=t.thumbnail)
        if t.requester:
            embed.set_footer(text=f"Requested by {t.requester}")
        badge = SOURCE_BADGES.get(t.source or "", "")
        embed.add_field(name="Source", value=f"{badge} {(t.source or 'unknown').capitalize()}", inline=True)
        embed.add_field(name="Loop", value=player.loop_mode.value, inline=True)
        embed.add_field(name="Volume", value=f"{int(player.volume * 100)}%", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="volume", description="Set playback volume (0-100)")
    @app_commands.describe(level="Volume level (0-100)")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 100]):
        player = await self.get_player(interaction.guild.id)
        player.volume = level / 100.0
        vc = interaction.guild.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = player.volume
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Volume set to **{level}%**", color=discord.Color.green())
        )

    @app_commands.command(name="loop", description="Set loop mode")
    @app_commands.describe(mode="Loop mode: off, single, or queue")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Off", value="off"),
        app_commands.Choice(name="Single", value="single"),
        app_commands.Choice(name="Queue", value="queue"),
    ])
    async def loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        player = await self.get_player(interaction.guild.id)
        player.loop_mode = LoopMode(mode.value)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Loop mode: **{mode.name}**", color=discord.Color.green())
        )

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, interaction: discord.Interaction):
        player = await self.get_player(interaction.guild.id)
        if not player.queue:
            await interaction.response.send_message("Queue is empty.", ephemeral=True)
            return
        player.shuffle()
        await interaction.response.send_message(
            embed=discord.Embed(description=f"Shuffled **{len(player.queue)}** tracks.", color=discord.Color.green())
        )

    @app_commands.command(name="remove", description="Remove a track from the queue by position")
    @app_commands.describe(position="Position in queue (1-based)")
    async def remove(self, interaction: discord.Interaction, position: int):
        player = await self.get_player(interaction.guild.id)
        track = player.remove(position)
        if track:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"Removed **{track.title}** from position {position}.",
                    color=discord.Color.orange(),
                )
            )
        else:
            await interaction.response.send_message(
                f"Invalid position. Queue has {len(player.queue)} tracks.",
                ephemeral=True,
            )

    @app_commands.command(name="disconnect", description="Disconnect from voice channel")
    async def disconnect(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            await interaction.response.defer()
            player = await self.get_player(interaction.guild.id)
            player.cancel_idle_timer()
            player.clear()
            vc.stop()
            await vc.disconnect()
            self.players.pop(interaction.guild.id, None)
            await interaction.followup.send(
                embed=discord.Embed(description="Disconnected.", color=discord.Color.orange())
            )
        else:
            await interaction.response.send_message("Not connected.", ephemeral=True)

    @app_commands.command(name="move", description="Move a track to a different position in the queue")
    @app_commands.describe(from_pos="Current position (1-based)", to_pos="New position (1-based)")
    async def move(self, interaction: discord.Interaction, from_pos: int, to_pos: int):
        player = await self.get_player(interaction.guild.id)
        track = player.move(from_pos, to_pos)
        if track:
            await interaction.response.send_message(
                embed=discord.Embed(
                    description=f"Moved **{track.title}** from position {from_pos} to {to_pos}.",
                    color=discord.Color.green(),
                )
            )
        else:
            await interaction.response.send_message(
                f"Invalid position(s). Queue has {len(player.queue)} tracks.",
                ephemeral=True,
            )

    @app_commands.command(name="lyrics", description="Show lyrics for the current track or a search query")
    @app_commands.describe(query="Artist and title, e.g. 'Never Gonna Give You Up Rick Astley' (optional if playing)")
    async def lyrics(self, interaction: discord.Interaction, query: Optional[str] = None):
        await interaction.response.defer()

        artist, title = None, None

        if query:
            # Try splitting "Title - Artist" or "Artist - Title" convention
            if " - " in query:
                parts = query.split(" - ", 1)
                artist, title = parts[0].strip(), parts[1].strip()
            else:
                title = query.strip()
        else:
            # Auto-populate from currently playing track
            player = await self.get_player(interaction.guild.id)
            if not player.current:
                await interaction.followup.send("Nothing is playing. Provide a `query` to search.", ephemeral=True)
                return
            track_title = player.current.title
            # Many YouTube titles are "Artist - Title"
            if " - " in track_title:
                parts = track_title.split(" - ", 1)
                artist, title = parts[0].strip(), parts[1].strip()
            else:
                title = track_title

        if not artist:
            await interaction.followup.send(
                f"Could not determine the artist for **{title}**. "
                "Try `/lyrics Artist - Title` (e.g. `/lyrics Rick Astley - Never Gonna Give You Up`).",
                ephemeral=True,
            )
            return

        try:
            url = f"https://api.lyrics.ovh/v1/{artist}/{title}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 404:
                        await interaction.followup.send(
                            f"No lyrics found for **{title}**{f' by {artist}' if artist else ''}.",
                            ephemeral=True,
                        )
                        return
                    if resp.status != 200:
                        await interaction.followup.send("Lyrics service unavailable. Try again later.", ephemeral=True)
                        return
                    data = await resp.json()
        except Exception as exc:
            log.warning("Lyrics fetch failed: %s", exc)
            await interaction.followup.send("Could not fetch lyrics right now.", ephemeral=True)
            return

        lyrics_text = data.get("lyrics", "").strip()
        if not lyrics_text:
            await interaction.followup.send("No lyrics found.", ephemeral=True)
            return

        truncated = len(lyrics_text) > 1800
        display = lyrics_text[:1800] + ("\n..." if truncated else "")

        embed = discord.Embed(
            title=f"Lyrics — {title}{f' by {artist}' if artist else ''}",
            description=display,
            color=0x1DB954,
        )
        if truncated:
            embed.set_footer(text="Lyrics truncated to fit Discord's limit.")
        await interaction.followup.send(embed=embed)

    # --- Config commands ---

    musicconfig_group = app_commands.Group(
        name="musicconfig",
        description="Configure music settings for this server",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @musicconfig_group.command(name="set", description="Set default music settings")
    @app_commands.describe(
        default_volume="Default volume percentage (1-100)",
        max_queue_size="Maximum queue size (1-1000)",
        fallback_service="Fallback service when YouTube stream fails",
    )
    @app_commands.choices(fallback_service=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="SoundCloud", value="soundcloud"),
    ])
    async def musicconfig_set(
        self,
        interaction: discord.Interaction,
        default_volume: Optional[app_commands.Range[int, 1, 100]] = None,
        max_queue_size: Optional[app_commands.Range[int, 1, 1000]] = None,
        fallback_service: Optional[app_commands.Choice[str]] = None,
    ):
        from dashboard import db

        gid = str(interaction.guild_id)
        parts = []
        if default_volume is not None:
            await db.set_guild_setting(gid, "music_default_volume", str(default_volume))
            parts.append(f"Default volume set to **{default_volume}%**")
        if max_queue_size is not None:
            await db.set_guild_setting(gid, "music_max_queue_size", str(max_queue_size))
            parts.append(f"Max queue size set to **{max_queue_size}**")
        if fallback_service is not None:
            await db.set_guild_setting(gid, "music_fallback_service", fallback_service.value)
            parts.append(f"Fallback service set to **{fallback_service.name}**")
        if not parts:
            await interaction.response.send_message("No changes specified.", ephemeral=True)
            return
        await interaction.response.send_message(". ".join(parts) + ".", ephemeral=True)

    @musicconfig_group.command(name="show", description="Show current music configuration")
    async def musicconfig_show(self, interaction: discord.Interaction):
        from dashboard import db

        gid = str(interaction.guild_id)
        volume = await db.get_guild_setting(gid, "music_default_volume", "50")
        max_queue = await db.get_guild_setting(gid, "music_max_queue_size", "500")
        fallback = await db.get_guild_setting(gid, "music_fallback_service", "youtube")
        embed = discord.Embed(title="Music Configuration", color=0x3498DB)
        embed.add_field(name="Default Volume", value=f"{volume}%")
        embed.add_field(name="Max Queue Size", value=max_queue)
        embed.add_field(name="Fallback Service", value=fallback.capitalize())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="history", description="Show recently played tracks")
    async def history(self, interaction: discord.Interaction):
        from dashboard import db
        rows = await db.get_track_history(str(interaction.guild_id), limit=25)
        if not rows:
            await interaction.response.send_message("No track history yet.", ephemeral=True)
            return
        view = HistoryView(rows)
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="crossfade", description="Set fade-in/out duration per track (0 = off)")
    @app_commands.describe(seconds="Fade duration in seconds (0-5)")
    async def crossfade(self, interaction: discord.Interaction,
                        seconds: app_commands.Range[int, 0, 5]):
        player = await self.get_player(interaction.guild.id)
        player.crossfade = seconds
        msg = f"Crossfade set to **{seconds}s**." if seconds > 0 else "Crossfade disabled."
        await interaction.response.send_message(
            embed=discord.Embed(description=msg, color=discord.Color.green())
        )

    # --- Filter commands ---

    filter_group = app_commands.Group(name="filter", description="Audio filter presets")

    @filter_group.command(name="set", description="Apply an audio filter preset")
    @app_commands.describe(name="Filter name")
    @app_commands.choices(name=[
        app_commands.Choice(name=k.capitalize(), value=k) for k in AUDIO_FILTERS
    ])
    async def filter_set(self, interaction: discord.Interaction, name: app_commands.Choice[str]):
        player = await self.get_player(interaction.guild.id)
        player.active_filter = name.value
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()) and player.current:
            # Reinsert current track at front of queue and restart to apply filter
            player.queue.insert(0, player.current)
            player.current = None
            vc.stop()
            msg = f"Filter **{name.name}** applied — restarting track."
        else:
            msg = f"Filter **{name.name}** set — takes effect on next track."
        await interaction.response.send_message(
            embed=discord.Embed(description=msg, color=discord.Color.green())
        )

    @filter_group.command(name="clear", description="Remove the active audio filter")
    async def filter_clear(self, interaction: discord.Interaction):
        player = await self.get_player(interaction.guild.id)
        player.active_filter = None
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()) and player.current:
            player.queue.insert(0, player.current)
            player.current = None
            vc.stop()
            msg = "Filter cleared — restarting track."
        else:
            msg = "Filter cleared."
        await interaction.response.send_message(
            embed=discord.Embed(description=msg, color=discord.Color.orange())
        )

    @filter_group.command(name="list", description="List available audio filter presets")
    async def filter_list(self, interaction: discord.Interaction):
        player = await self.get_player(interaction.guild.id)
        active = player.active_filter or "none"
        lines = []
        for k in AUDIO_FILTERS:
            marker = "**" if k == active else ""
            lines.append(f"{marker}`{k}`{marker}")
        embed = discord.Embed(
            title="Audio Filters",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Active: {active}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        # Clean up player when the bot is force-disconnected from voice
        if member.id != self.bot.user.id:
            return
        if before.channel is not None and after.channel is None:
            player = self.players.pop(member.guild.id, None)
            if player:
                player.clear()
                player.cancel_idle_timer()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        player = self.players.pop(guild.id, None)
        if player:
            player.cancel_idle_timer()


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
