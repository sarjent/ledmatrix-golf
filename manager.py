"""
PGA Tour Leaderboard Plugin for LEDMatrix

Displays the top players from the current PGA Tour leaderboard using ESPN data.
Shows tournaments within a configurable date range and refreshes at user-defined intervals.

API Version: 1.2.0
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

from src.plugin_system.base_plugin import BasePlugin, VegasDisplayMode
from src.common import APIHelper, TextHelper, ScrollHelper, LogoHelper

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
        self.scroll_helper = ScrollHelper(
            display_width=self.display_width,
            display_height=self.display_height,
            logger=self.logger
        )
        # Configure scrolling for smooth, readable display
        self.scroll_helper.set_scroll_speed(30.0)  # 30 pixels per second for readability
        self.scroll_helper.set_target_fps(120)  # 120 FPS for smooth scrolling

        self.logo_helper = LogoHelper(
            display_width=self.display_width,
            display_height=self.display_height,
            logger=self.logger
        )

        # Load configuration
        self._load_config()

        # Load fonts
        self._load_fonts()

        # Load PGA Tour logo
        self._load_logo()

        # State tracking
        self.current_tournament = None
        self.leaderboard_data = []
        self.previous_tournament = None
        self.previous_leaderboard_data = []
        self.last_update = None
        self.current_player_index = 0
        self.scroll_image = None

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

    def _load_logo(self) -> None:
        """Load the PGA Tour logo."""
        try:
            logo_path = Path("assets/sports/pga_logos/pga_logo.png")
            # Use larger logo size to match news ticker style
            # Max height is scroll area (display_height - 8) minus 2px padding
            scroll_height = self.display_height - 8
            self.pga_logo = self.logo_helper.load_logo(
                "PGA",
                logo_path,
                max_width=36,  # Increased from 20 for better visibility
                max_height=scroll_height - 2  # Full scroll height minus padding
            )
            if self.pga_logo:
                self.logger.debug(f"Loaded PGA Tour logo from {logo_path} (size: {self.pga_logo.width}x{self.pga_logo.height})")
            else:
                self.logger.warning(f"PGA Tour logo not found at {logo_path}")
                self.pga_logo = None
        except Exception as e:
            self.logger.error(f"Error loading PGA Tour logo: {e}")
            self.pga_logo = None

    def update(self) -> None:
        """
        Fetch PGA Tour leaderboard data from ESPN.
        Only fetches tournaments within the configured date range.
        """
        try:
            # Check if we need to update (respects update_interval)
            # Use a shorter interval when we have no current tournament,
            # so we detect new tournaments faster during transition periods.
            effective_interval = self.update_interval_seconds
            if not self.current_tournament and self.last_update:
                # Refresh every 2 minutes when waiting for a new tournament
                effective_interval = min(self.update_interval_seconds, 120)

            if self.last_update:
                time_since_update = (datetime.now() - self.last_update).total_seconds()
                if time_since_update < effective_interval:
                    self.logger.debug(f"Skipping update, last update was {time_since_update:.0f}s ago")
                    return

            # Fetch current PGA Tour events
            # No cache_key: the update_interval throttle above handles rate limiting,
            # and skipping the cache ensures we always get fresh data from ESPN.
            # In-memory state (current_tournament/previous_tournament) provides
            # display continuity if the API call fails.
            data = self.api_helper.get(
                url="https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
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

            # Invalidate cached scroll image so display() will regenerate it with new data
            self.scroll_image = None

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
            most_recent_completed = None
            most_recent_completed_date = None

            for event in events:
                # Parse tournament date
                event_date_str = event.get('date')
                if not event_date_str:
                    continue

                try:
                    event_date = datetime.fromisoformat(event_date_str.replace('Z', '+00:00'))
                    # Remove timezone info for comparison
                    event_date = event_date.replace(tzinfo=None)

                    # Get tournament status
                    event_status = event.get('status', {}).get('type', {}).get('state', '')

                    # Tournament is valid if:
                    # 1. Status is "in" (currently in progress) - always show active tournaments
                    # 2. Status is "pre" (scheduled) and within date range
                    # The ESPN API date is the tournament START date, so we check
                    # if the start date is within the range (not requiring today <= event_date)
                    if event_status == 'in':
                        # Tournament is actively in progress - always show it
                        valid_tournament = event
                        self.logger.debug(f"Found in-progress tournament: {event.get('name')}")
                        break
                    elif event_status == 'pre' and event_date <= date_threshold:
                        # Upcoming tournament within date range
                        valid_tournament = event
                        self.logger.debug(f"Found upcoming tournament: {event.get('name')}")
                        break

                    # Track most recent completed tournament as fallback
                    if event_status == 'post' and event_date < today:
                        if most_recent_completed is None or event_date > most_recent_completed_date:
                            most_recent_completed = event
                            most_recent_completed_date = event_date

                except Exception as e:
                    self.logger.debug(f"Error parsing date {event_date_str}: {e}")
                    continue

            # If we found a completed tournament in current response, store it as fallback
            if most_recent_completed:
                self._process_previous_tournament(most_recent_completed)

            if not valid_tournament:
                self.logger.info(f"No tournaments found within {self.tournament_date_range} days")
                self.current_tournament = None
                self.leaderboard_data = []
                return

            # Detect tournament change
            new_name = valid_tournament.get('name', 'PGA Tour')
            old_name = self.current_tournament.get('name') if self.current_tournament else None
            if old_name and old_name != new_name:
                self.logger.info(f"Tournament changed: '{old_name}' -> '{new_name}'")

            # Extract tournament info
            self.current_tournament = {
                'name': new_name,
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
            # Use 'order' field (more reliable), fall back to 'sortOrder' if not available
            sorted_competitors = sorted(
                competitors,
                key=lambda x: self._parse_position(x.get('order') or x.get('sortOrder', 999))
            )

            self.leaderboard_data = []
            for competitor in sorted_competitors[:self.max_players]:
                try:
                    athlete = competitor.get('athlete', {})
                    stats = competitor.get('statistics', [])

                    # Extract score/position (prefer 'order' field, fall back to 'sortOrder')
                    position = competitor.get('order') or competitor.get('sortOrder', '')
                    score_display = self._get_score_display(competitor, stats)

                    # Extract holes completed ("thru")
                    thru_display = self._get_thru_display(stats)

                    # Check if player is currently on the course
                    is_on_course = self._is_player_on_course(stats)

                    player_data = {
                        'position': position,
                        'name': athlete.get('displayName', 'Unknown'),
                        'short_name': athlete.get('shortName', athlete.get('displayName', 'Unknown')),
                        'score': score_display,
                        'thru': thru_display,
                        'on_course': is_on_course,
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
            # Primary: Get score directly from competitor object (most reliable)
            score = competitor.get('score')
            if score is not None:
                return str(score)

            # Fallback: Try to get score from statistics
            for stat in stats:
                if stat.get('name') == 'score':
                    score_value = stat.get('displayValue', stat.get('value'))
                    if score_value:
                        return str(score_value)

            return "E"  # Default to even par

        except Exception as e:
            self.logger.debug(f"Error getting score display: {e}")
            return "E"

    def _get_thru_display(self, stats: List[Dict]) -> str:
        """
        Get the display string for holes completed.

        Args:
            stats: Statistics list

        Returns:
            Thru display string (e.g., "F", "12", "18*" for finished, through 12, etc.)
        """
        try:
            for stat in stats:
                if stat.get('name') == 'thru':
                    thru_value = stat.get('displayValue', stat.get('value'))
                    if thru_value:
                        return str(thru_value)
            return "F"  # Default to finished

        except Exception as e:
            self.logger.debug(f"Error getting thru display: {e}")
            return "F"

    def _is_player_on_course(self, stats: List[Dict]) -> bool:
        """
        Check if player is currently on the course.
        A player is considered on course if they have started but not finished their round.

        Args:
            stats: Statistics list

        Returns:
            True if player is currently on the course, False otherwise
        """
        try:
            thru_value = None
            for stat in stats:
                if stat.get('name') == 'thru':
                    thru_value = stat.get('displayValue', stat.get('value'))
                    break

            # Player is on course if thru is not "F" (finished) and not empty
            if thru_value and str(thru_value).upper() != 'F':
                # Check if it's a valid hole number (indicates they're playing)
                try:
                    hole_num = int(str(thru_value))
                    return 1 <= hole_num <= 18
                except ValueError:
                    # If thru contains "*" or other indicators, still check
                    return '*' in str(thru_value) or str(thru_value).isdigit()

            return False

        except Exception as e:
            self.logger.debug(f"Error checking if player on course: {e}")
            return False

    def _fetch_previous_tournament(self) -> None:
        """
        Fetch the most recent completed tournament as fallback.
        Looks back up to 30 days for a completed tournament.
        Only called if current scoreboard didn't contain a completed tournament.
        """
        try:
            # If we already have a previous tournament from current response, skip
            if self.previous_tournament:
                self.logger.debug("Already have previous tournament from current response")
                return

            today = datetime.now()

            # Search backwards day by day to find most recent completed tournament
            # Check every 3 days to balance thoroughness with API calls
            for days_back in range(1, 31, 3):  # Check 1, 4, 7, 10, 13...28 days back
                date_to_check = today - timedelta(days=days_back)
                date_str = date_to_check.strftime('%Y%m%d')

                data = self.api_helper.get(
                    url=f"https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard",
                    params={'dates': date_str}
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
                            self.logger.info(f"Found previous tournament {days_back} days back")
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
            # Use 'order' field (more reliable), fall back to 'sortOrder' if not available
            sorted_competitors = sorted(
                competitors,
                key=lambda x: self._parse_position(x.get('order') or x.get('sortOrder', 999))
            )

            self.previous_leaderboard_data = []
            for competitor in sorted_competitors[:self.fallback_players]:
                try:
                    athlete = competitor.get('athlete', {})
                    stats = competitor.get('statistics', [])

                    # Extract score/position (prefer 'order' field, fall back to 'sortOrder')
                    position = competitor.get('order') or competitor.get('sortOrder', '')
                    score_display = self._get_score_display(competitor, stats)

                    # Extract holes completed ("thru") - will be "F" for completed tournaments
                    thru_display = self._get_thru_display(stats)

                    # Previous tournaments are completed, so no one is on course
                    is_on_course = False

                    player_data = {
                        'position': position,
                        'name': athlete.get('displayName', 'Unknown'),
                        'short_name': athlete.get('shortName', athlete.get('displayName', 'Unknown')),
                        'score': score_display,
                        'thru': thru_display,
                        'on_course': is_on_course,
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
        Display the PGA Tour leaderboard with horizontal scrolling.

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

            # Create or update the scrolling image (players only)
            if self.scroll_image is None or force_clear:
                self.scroll_image = self._create_scroll_image(tournament, leaderboard, is_previous)
                # Update scroll helper's display_height to match scroll area (not full display)
                scroll_height = self.display_height - 8  # Reserve 8 pixels for tournament bar
                self.scroll_helper.display_height = scroll_height
                self.scroll_helper.set_scrolling_image(self.scroll_image)

            # Update scroll position
            self.scroll_helper.update_scroll_position()

            # Get visible portion from scroll helper
            scroll_frame = self.scroll_helper.get_visible_portion()

            # Create composite image with scrolling players + static tournament name
            if scroll_frame:
                composite = Image.new('RGB', (self.display_width, self.display_height), (0, 0, 0))

                # Paste scrolling player data at top
                composite.paste(scroll_frame, (0, 0))

                # Draw static tournament bar at bottom
                tournament_bar = self._create_tournament_bar(tournament, is_previous)
                composite.paste(tournament_bar, (0, self.display_height - 8))

                # Update display
                self.display_manager.image = composite
                self.display_manager.update_display()

            tournament_type = "previous" if is_previous else "current"
            self.logger.debug(f"Scrolling {tournament_type} PGA Tour leaderboard: {tournament['name']}")

        except Exception as e:
            self.logger.error(f"Error displaying leaderboard: {e}", exc_info=True)
            self._display_error()

    def _create_scroll_image(self, tournament: Dict, leaderboard: List[Dict], is_previous: bool) -> Image.Image:
        """
        Create the scrolling image with PGA logo and player standings.
        Tournament name is displayed separately in a static bar at bottom.

        Args:
            tournament: Tournament data
            leaderboard: List of player data
            is_previous: Whether this is a previous tournament

        Returns:
            PIL Image for scrolling (logo + players)
        """
        # Calculate content width
        logo_width = self.pga_logo.width if self.pga_logo else 0
        spacing = 6  # Increased spacing for larger logo

        # Build the leaderboard text (players only, no tournament name)
        content_parts = []

        for i, player in enumerate(leaderboard):
            position = player['position']
            name = player['short_name']
            score = player['score']
            thru = player.get('thru', 'F')
            on_course = player.get('on_course', False)

            # Add asterisk prefix if player is on course
            name_prefix = "*" if on_course else ""

            # Build player string with thru info
            player_str = f"{position}. {name_prefix}{name} {score}"

            # Add thru information if not finished
            if thru and thru.upper() != 'F':
                player_str += f" ({thru})"

            content_parts.append(player_str)

        # Join with separator
        separator = " | "
        content_text = separator.join(content_parts)

        # Estimate total width (rough approximation)
        # Each character is roughly 6 pixels wide with this font
        char_width = 6
        text_width = len(content_text) * char_width
        total_width = logo_width + spacing + text_width + self.display_width  # Add buffer for smooth scrolling

        # Calculate scroll area height (reserve space for tournament bar)
        scroll_height = self.display_height - 8

        # Create the scrolling image (logo + players)
        img = Image.new('RGB', (total_width, scroll_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Start drawing - logo comes first
        current_x = self.display_width  # Start offscreen right for smooth entry

        # Draw PGA logo at the start (vertically centered in scroll area)
        if self.pga_logo:
            logo_y = (scroll_height - self.pga_logo.height) // 2
            img.paste(self.pga_logo, (current_x, logo_y), self.pga_logo if self.pga_logo.mode == 'RGBA' else None)
            current_x += logo_width + spacing

        # Draw the leaderboard content
        y_pos = (scroll_height // 2) - (self.font_size // 2)

        # Draw each part with appropriate color
        for i, part in enumerate(content_parts):
            # Determine color (highlight first 3 players)
            if i < 3:
                # Top 3 players
                color = self.highlight_color
            else:
                # Other players
                color = self.text_color

            draw.text((current_x, y_pos), part, font=self.font, fill=color)

            # Calculate width of this part
            bbox = draw.textbbox((current_x, y_pos), part, font=self.font)
            part_width = bbox[2] - bbox[0]
            current_x += part_width

            # Add separator
            if i < len(content_parts) - 1:
                draw.text((current_x, y_pos), separator, font=self.font, fill=(0, 255, 0))
                sep_bbox = draw.textbbox((current_x, y_pos), separator, font=self.font)
                current_x += sep_bbox[2] - sep_bbox[0]

        return img

    def _create_tournament_bar(self, tournament: Dict, is_previous: bool) -> Image.Image:
        """
        Create a static bar with centered tournament name (no logo).

        Args:
            tournament: Tournament data
            is_previous: Whether this is a previous tournament

        Returns:
            PIL Image for static tournament bar (8 pixels high)
        """
        # Create 8-pixel high bar
        bar = Image.new('RGB', (self.display_width, 8), (0, 0, 0))
        draw = ImageDraw.Draw(bar)

        # Draw tournament name
        tournament_prefix = "PREV: " if is_previous else ""
        tournament_text = f"{tournament_prefix}{tournament['name']}"

        # Calculate text dimensions
        bbox = draw.textbbox((0, 0), tournament_text, font=self.font)
        text_width = bbox[2] - bbox[0]

        # Truncate tournament name if it's too long to fit display
        max_width = self.display_width - 4  # Leave 2px margin on each side
        if text_width > max_width:
            # Truncate text to fit
            while len(tournament_text) > 3 and text_width > max_width:
                tournament_text = tournament_text[:-4] + "..."
                bbox = draw.textbbox((0, 0), tournament_text, font=self.font)
                text_width = bbox[2] - bbox[0]

        # Center the text horizontally
        x_pos = (self.display_width - text_width) // 2
        y_pos = 1  # Centered vertically in 8px bar for 6px font

        # Draw tournament name in highlight color (centered)
        draw.text((x_pos, y_pos), tournament_text, font=self.font, fill=self.highlight_color)

        return bar

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

    # -------------------------------------------------------------------------
    # Vegas scroll mode support
    # -------------------------------------------------------------------------

    def get_vegas_content_type(self) -> str:
        """Report as multi-item content so Vegas uses SCROLL mode by default."""
        return 'multi'

    def get_vegas_content(self) -> Optional[List[Image.Image]]:
        """
        Return one image per player for Vegas scroll mode.

        Vegas composes these individually into the continuous scroll stream.
        Uses current leaderboard data, falling back to previous tournament data.
        Returns None if no data is loaded yet.
        """
        leaderboard = self.leaderboard_data or self.previous_leaderboard_data
        if not leaderboard:
            return None

        images = []
        for i, player in enumerate(leaderboard):
            img = self._create_player_item(player, i)
            if img:
                images.append(img)

        return images if images else None

    def _create_player_item(self, player: Dict[str, Any], position_index: int) -> Image.Image:
        """
        Create a single player item image for Vegas scroll mode.

        Each image is display_height tall and contains the player's
        position, name, score, and holes-thru information.

        Args:
            player: Player data dictionary
            position_index: 0-based index (used for highlight color on top 3)

        Returns:
            PIL Image for this player
        """
        position = player['position']
        name = player['short_name']
        score = player['score']
        thru = player.get('thru', 'F')
        on_course = player.get('on_course', False)

        name_prefix = "*" if on_course else ""
        player_str = f"{position}. {name_prefix}{name} {score}"
        if thru and thru.upper() != 'F':
            player_str += f" ({thru})"

        # Measure text width
        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        bbox = temp_draw.textbbox((0, 0), player_str, font=self.font)
        text_width = bbox[2] - bbox[0]

        img = Image.new('RGB', (text_width + 4, self.display_height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Center text vertically
        y = (self.display_height - self.font_size) // 2

        # Top 3 players get highlight color
        color = self.highlight_color if position_index < 3 else self.text_color
        draw.text((2, y), player_str, font=self.font, fill=color)

        return img

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
        self.scroll_image = None
        self.pga_logo = None

        # Clear scroll helper cache
        if self.scroll_helper:
            self.scroll_helper.clear_cache()

        self.logger.info("PGA Tour Leaderboard plugin cleaned up")
