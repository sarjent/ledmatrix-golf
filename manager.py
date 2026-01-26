"""
PGA Tour Leaderboard Plugin for LEDMatrix

Displays the top players from the current PGA Tour leaderboard using ESPN data.
Shows tournaments within a configurable date range and refreshes at user-defined intervals.

API Version: 1.1.0
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin
from src.common import APIHelper, TextHelper

logger = logging.getLogger(__name__)


class PGATourLeaderboardPlugin(BasePlugin):
    """
    PGA Tour Leaderboard plugin that displays top players from current tournaments.

    Configuration options:
        enabled (bool): Enable/disable plugin (default: true)
        display_duration (float): Display duration in seconds (default: 15)
        update_interval (int): Data refresh interval in seconds (default: 600)
        max_players (int): Maximum number of players to display (default: 10)
        fallback_players (int): Number of players from previous tournament to show (default: 5)
        tournament_date_range (int): Days to look ahead for tournaments (default: 7)
        font_size (int): Font size for text (default: 6)
        font_name (str): Font file name (default: "4x6-font.ttf")
        text_color (dict): RGB color for text (default: white)
        highlight_color (dict): RGB color for highlighting leaders (default: gold)
    """

    def __init__(self, plugin_id: str, config: Dict[str, Any],
                 display_manager, cache_manager, plugin_manager):
        """Initialize the PGA Tour Leaderboard plugin."""
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        # Get display dimensions
        self.display_width = display_manager.matrix.width
        self.display_height = display_manager.matrix.height

        # Initialize common helpers
        self.api_helper = APIHelper(
            cache_manager=cache_manager,
            logger=self.logger
        )
        self.text_helper = TextHelper(logger=self.logger)

        # Load configuration
        self._load_config()

        # Load fonts
        self._load_fonts()

        # State tracking
        self.current_tournament = None
        self.leaderboard_data = []
        self.previous_tournament = None
        self.previous_leaderboard_data = []
        self.last_update = None
        self.current_player_index = 0

        self.logger.info("PGA Tour Leaderboard plugin initialized")

    def _load_config(self) -> None:
        """Load and validate configuration."""
        self.max_players = self.config.get('max_players', 10)
        self.fallback_players = self.config.get('fallback_players', 5)
        self.tournament_date_range = self.config.get('tournament_date_range', 7)
        self.update_interval_seconds = self.config.get('update_interval', 600)
        self.font_size = self.config.get('font_size', 6)
        self.font_name = self.config.get('font_name', '4x6-font.ttf')

        # Parse text color
        text_color_config = self.config.get('text_color', {'r': 255, 'g': 255, 'b': 255})
        self.text_color = (
            text_color_config.get('r', 255),
            text_color_config.get('g', 255),
            text_color_config.get('b', 255)
        )

        # Parse highlight color (for leaders)
        highlight_color_config = self.config.get('highlight_color', {'r': 255, 'g': 215, 'b': 0})
        self.highlight_color = (
            highlight_color_config.get('r', 255),
            highlight_color_config.get('g', 215),
            highlight_color_config.get('b', 0)
        )

    def _load_fonts(self) -> None:
        """Load fonts for display."""
        try:
            font_path = Path("assets/fonts") / self.font_name
            if font_path.exists():
                self.font = ImageFont.truetype(str(font_path), self.font_size)
                self.logger.debug(f"Loaded font: {self.font_name} (size {self.font_size})")
            else:
                self.font = ImageFont.load_default()
                self.logger.warning(f"Font not found: {font_path}, using default")
        except Exception as e:
            self.logger.error(f"Error loading font: {e}")
            self.font = ImageFont.load_default()

    def update(self) -> None:
        """
        Fetch PGA Tour leaderboard data from ESPN.
        Only fetches tournaments within the configured date range.
        """
        try:
            # Check if we need to update (respects update_interval)
            if self.last_update:
                time_since_update = (datetime.now() - self.last_update).total_seconds()
                if time_since_update < self.update_interval_seconds:
                    self.logger.debug(f"Skipping update, last update was {time_since_update:.0f}s ago")
                    return

            # Fetch current PGA Tour events
            cache_key = f"{self.plugin_id}_pga_leaderboard"
            data = self.api_helper.get(
                url="https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard",
                cache_key=cache_key,
                cache_ttl=self.update_interval_seconds
            )

            if not data:
                self.logger.warning("Failed to fetch PGA Tour data from ESPN")
                return

            # Process the data
            self._process_tournament_data(data)

            # If no current tournament found, try to fetch previous tournament as fallback
            if not self.current_tournament:
                self.logger.info("No current tournament found, fetching previous tournament as fallback")
                self._fetch_previous_tournament()

            self.last_update = datetime.now()

            if self.current_tournament:
                self.logger.info(
                    f"Updated PGA Tour data: {self.current_tournament['name']} "
                    f"({len(self.leaderboard_data)} players)"
                )
            elif self.previous_tournament:
                self.logger.info(
                    f"Using previous tournament: {self.previous_tournament['name']} "
                    f"({len(self.previous_leaderboard_data)} players)"
                )
            else:
                self.logger.info("No active or previous tournaments found")

        except Exception as e:
            self.logger.error(f"Error updating PGA Tour data: {e}", exc_info=True)

    def _process_tournament_data(self, data: Dict) -> None:
        """
        Process ESPN API response and extract tournament and leaderboard data.

        Args:
            data: ESPN API response dictionary
        """
        try:
            events = data.get('events', [])

            if not events:
                self.logger.warning("No events found in ESPN response")
                self.current_tournament = None
                self.leaderboard_data = []
                return

            # Filter tournaments by date range
            today = datetime.now()
            date_threshold = today + timedelta(days=self.tournament_date_range)

            valid_tournament = None
            for event in events:
                # Parse tournament date
                event_date_str = event.get('date')
                if not event_date_str:
                    continue

                try:
                    event_date = datetime.fromisoformat(event_date_str.replace('Z', '+00:00'))
                    # Remove timezone info for comparison
                    event_date = event_date.replace(tzinfo=None)

                    # Check if tournament is within date range
                    if today <= event_date <= date_threshold:
                        valid_tournament = event
                        break
                except Exception as e:
                    self.logger.debug(f"Error parsing date {event_date_str}: {e}")
                    continue

            if not valid_tournament:
                self.logger.info(f"No tournaments found within {self.tournament_date_range} days")
                self.current_tournament = None
                self.leaderboard_data = []
                return

            # Extract tournament info
            self.current_tournament = {
                'name': valid_tournament.get('name', 'PGA Tour'),
                'date': valid_tournament.get('date', ''),
                'status': valid_tournament.get('status', 'scheduled')
            }

            # Extract leaderboard from competition
            competitions = valid_tournament.get('competitions', [])
            if not competitions:
                self.logger.warning("No competitions found in tournament")
                self.leaderboard_data = []
                return

            competition = competitions[0]
            competitors = competition.get('competitors', [])

            # Sort by position and extract top players
            sorted_competitors = sorted(
                competitors,
                key=lambda x: self._parse_position(x.get('sortOrder', 999))
            )

            self.leaderboard_data = []
            for competitor in sorted_competitors[:self.max_players]:
                try:
                    athlete = competitor.get('athlete', {})
                    stats = competitor.get('statistics', [])

                    # Extract score/position
                    position = competitor.get('sortOrder', '')
                    score_display = self._get_score_display(competitor, stats)

                    player_data = {
                        'position': position,
                        'name': athlete.get('displayName', 'Unknown'),
                        'short_name': athlete.get('shortName', athlete.get('displayName', 'Unknown')),
                        'score': score_display,
                        'status': competitor.get('status', '')
                    }

                    self.leaderboard_data.append(player_data)

                except Exception as e:
                    self.logger.debug(f"Error processing competitor: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error processing tournament data: {e}", exc_info=True)
            self.current_tournament = None
            self.leaderboard_data = []

    def _parse_position(self, position: Any) -> int:
        """
        Parse position to integer for sorting.

        Args:
            position: Position value (may be int, str, or other)

        Returns:
            Integer position for sorting
        """
        try:
            return int(position)
        except (ValueError, TypeError):
            return 999  # Place unparseable positions at the end

    def _get_score_display(self, competitor: Dict, stats: List[Dict]) -> str:
        """
        Get the display string for player's score.

        Args:
            competitor: Competitor data dictionary
            stats: Statistics list

        Returns:
            Score display string (e.g., "-5", "E", "+2")
        """
        try:
            # Try to get score from statistics
            for stat in stats:
                if stat.get('name') == 'score':
                    score_value = stat.get('displayValue', stat.get('value'))
                    if score_value:
                        return str(score_value)

            # Fallback to competitor score
            score = competitor.get('score')
            if score:
                return str(score)

            return "E"  # Default to even par

        except Exception as e:
            self.logger.debug(f"Error getting score display: {e}")
            return "E"

    def _fetch_previous_tournament(self) -> None:
        """
        Fetch the most recent completed tournament as fallback.
        Looks back up to 30 days for a completed tournament.
        """
        try:
            today = datetime.now()

            # Try fetching data from previous weeks
            for days_back in range(7, 31, 7):  # Check 7, 14, 21, 28 days back
                date_to_check = today - timedelta(days=days_back)
                date_str = date_to_check.strftime('%Y%m%d')

                cache_key = f"{self.plugin_id}_pga_previous_{date_str}"
                data = self.api_helper.get(
                    url=f"https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard",
                    params={'dates': date_str},
                    cache_key=cache_key,
                    cache_ttl=86400  # Cache for 24 hours
                )

                if not data:
                    continue

                events = data.get('events', [])
                if not events:
                    continue

                # Look for completed tournament
                for event in events:
                    event_status = event.get('status', {}).get('type', {}).get('state', '')
                    if event_status == 'post':  # Tournament is completed
                        self._process_previous_tournament(event)
                        if self.previous_tournament:
                            return

            self.logger.info("No previous tournaments found in the last 30 days")

        except Exception as e:
            self.logger.error(f"Error fetching previous tournament: {e}", exc_info=True)

    def _process_previous_tournament(self, event: Dict) -> None:
        """
        Process previous tournament data for fallback display.

        Args:
            event: Tournament event dictionary from ESPN API
        """
        try:
            # Extract tournament info
            self.previous_tournament = {
                'name': event.get('name', 'PGA Tour'),
                'date': event.get('date', ''),
                'status': 'completed'
            }

            # Extract leaderboard from competition
            competitions = event.get('competitions', [])
            if not competitions:
                self.previous_tournament = None
                self.previous_leaderboard_data = []
                return

            competition = competitions[0]
            competitors = competition.get('competitors', [])

            # Sort by position and extract top players (limited to fallback_players)
            sorted_competitors = sorted(
                competitors,
                key=lambda x: self._parse_position(x.get('sortOrder', 999))
            )

            self.previous_leaderboard_data = []
            for competitor in sorted_competitors[:self.fallback_players]:
                try:
                    athlete = competitor.get('athlete', {})
                    stats = competitor.get('statistics', [])

                    # Extract score/position
                    position = competitor.get('sortOrder', '')
                    score_display = self._get_score_display(competitor, stats)

                    player_data = {
                        'position': position,
                        'name': athlete.get('displayName', 'Unknown'),
                        'short_name': athlete.get('shortName', athlete.get('displayName', 'Unknown')),
                        'score': score_display,
                        'status': competitor.get('status', '')
                    }

                    self.previous_leaderboard_data.append(player_data)

                except Exception as e:
                    self.logger.debug(f"Error processing previous tournament competitor: {e}")
                    continue

            self.logger.info(
                f"Loaded previous tournament: {self.previous_tournament['name']} "
                f"with {len(self.previous_leaderboard_data)} players"
            )

        except Exception as e:
            self.logger.error(f"Error processing previous tournament: {e}", exc_info=True)
            self.previous_tournament = None
            self.previous_leaderboard_data = []

    def display(self, force_clear: bool = False) -> None:
        """
        Display the PGA Tour leaderboard.

        Args:
            force_clear: If True, clear display before rendering
        """
        try:
            if force_clear:
                self.display_manager.clear()

            # Determine which data to display (current or previous tournament)
            tournament = None
            leaderboard = []
            is_previous = False

            if self.current_tournament and self.leaderboard_data:
                tournament = self.current_tournament
                leaderboard = self.leaderboard_data
                is_previous = False
            elif self.previous_tournament and self.previous_leaderboard_data:
                tournament = self.previous_tournament
                leaderboard = self.previous_leaderboard_data
                is_previous = True
            else:
                self._display_no_data()
                return

            # Create display image
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Draw tournament name at the top with "PREV:" prefix if showing previous tournament
            tournament_prefix = "PREV: " if is_previous else ""
            tournament_name = self._truncate_text(f"{tournament_prefix}{tournament['name']}", 32)
            draw.text((2, 1), tournament_name, font=self.font, fill=self.text_color)

            # Draw leaderboard (starting at y=10 to leave room for tournament name)
            y_offset = 10
            line_height = self.font_size + 2

            # Calculate how many players we can fit on screen
            available_height = self.display_height - y_offset - 2
            max_visible_players = min(
                len(leaderboard),
                available_height // line_height
            )

            # Display players
            for i in range(max_visible_players):
                player = leaderboard[i]
                y_pos = y_offset + (i * line_height)

                # Determine color (highlight leader/top 3)
                color = self.highlight_color if i < 3 else self.text_color

                # Format: "1. J.Smith -5"
                position = player['position']
                name = self._truncate_text(player['short_name'], 12)
                score = player['score']

                line_text = f"{position}. {name} {score}"
                draw.text((2, y_pos), line_text, font=self.font, fill=color)

            # Update display
            self.display_manager.image = img
            self.display_manager.update_display()

            tournament_type = "previous" if is_previous else "current"
            self.logger.debug(f"Displayed {tournament_type} PGA Tour leaderboard: {tournament['name']}")

        except Exception as e:
            self.logger.error(f"Error displaying leaderboard: {e}", exc_info=True)
            self._display_error()

    def _display_no_data(self) -> None:
        """Display a message when no tournament data is available."""
        try:
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            message = "No PGA Tour"
            message2 = "tournaments"

            # Calculate center position
            bbox1 = draw.textbbox((0, 0), message, font=self.font)
            text_width1 = bbox1[2] - bbox1[0]
            x1 = (self.display_width - text_width1) // 2

            bbox2 = draw.textbbox((0, 0), message2, font=self.font)
            text_width2 = bbox2[2] - bbox2[0]
            x2 = (self.display_width - text_width2) // 2

            y1 = (self.display_height // 2) - self.font_size - 2
            y2 = (self.display_height // 2) + 2

            draw.text((x1, y1), message, font=self.font, fill=self.text_color)
            draw.text((x2, y2), message2, font=self.font, fill=self.text_color)

            self.display_manager.image = img
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying no data message: {e}")

    def _display_error(self) -> None:
        """Display an error message."""
        try:
            img = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))
            draw = ImageDraw.Draw(img)

            message = "Error loading"
            message2 = "leaderboard"

            bbox1 = draw.textbbox((0, 0), message, font=self.font)
            text_width1 = bbox1[2] - bbox1[0]
            x1 = (self.display_width - text_width1) // 2

            bbox2 = draw.textbbox((0, 0), message2, font=self.font)
            text_width2 = bbox2[2] - bbox2[0]
            x2 = (self.display_width - text_width2) // 2

            y1 = (self.display_height // 2) - self.font_size - 2
            y2 = (self.display_height // 2) + 2

            # Display in red
            error_color = (255, 0, 0)
            draw.text((x1, y1), message, font=self.font, fill=error_color)
            draw.text((x2, y2), message2, font=self.font, fill=error_color)

            self.display_manager.image = img
            self.display_manager.update_display()

        except Exception as e:
            self.logger.error(f"Error displaying error message: {e}")

    def _truncate_text(self, text: str, max_length: int) -> str:
        """
        Truncate text to fit within max_length characters.

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text
        """
        if len(text) <= max_length:
            return text
        return text[:max_length - 1] + "."

    def get_display_duration(self) -> float:
        """Get display duration from config."""
        return self.config.get('display_duration', 15.0)

    def validate_config(self) -> bool:
        """Validate plugin configuration."""
        # Call parent validation first
        if not super().validate_config():
            return False

        # Validate max_players
        max_players = self.config.get('max_players', 10)
        if not isinstance(max_players, int) or max_players < 1 or max_players > 20:
            self.logger.error("'max_players' must be an integer between 1 and 20")
            return False

        # Validate tournament_date_range
        date_range = self.config.get('tournament_date_range', 7)
        if not isinstance(date_range, int) or date_range < 0 or date_range > 30:
            self.logger.error("'tournament_date_range' must be an integer between 0 and 30")
            return False

        return True

    def get_info(self) -> Dict[str, Any]:
        """Return plugin info for web UI."""
        info = super().get_info()
        info.update({
            'current_tournament': self.current_tournament.get('name') if self.current_tournament else None,
            'players_count': len(self.leaderboard_data),
            'previous_tournament': self.previous_tournament.get('name') if self.previous_tournament else None,
            'previous_players_count': len(self.previous_leaderboard_data),
            'last_update': self.last_update.isoformat() if self.last_update else None
        })
        return info

    def on_config_change(self, new_config: Dict[str, Any]) -> None:
        """Handle configuration changes."""
        super().on_config_change(new_config)

        # Reload configuration
        self._load_config()

        # Reload fonts if font settings changed
        new_font_name = new_config.get('font_name', '4x6-font.ttf')
        new_font_size = new_config.get('font_size', 6)
        if new_font_name != self.font_name or new_font_size != self.font_size:
            self._load_fonts()

        self.logger.info("Configuration updated, reloading settings")

    def cleanup(self) -> None:
        """Cleanup resources when plugin is unloaded."""
        self.leaderboard_data = []
        self.current_tournament = None
        self.previous_leaderboard_data = []
        self.previous_tournament = None
        self.logger.info("PGA Tour Leaderboard plugin cleaned up")
