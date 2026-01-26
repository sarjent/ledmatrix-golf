# PGA Tour Leaderboard Plugin

A custom plugin for the [LEDMatrix project](https://github.com/ryderdamen/LEDMatrix) that displays the top players from the current PGA Tour leaderboard using ESPN data.

## Features

- 📊 Displays top 10 players (configurable) from current PGA Tour tournaments
- 🔙 **NEW v1.1.0**: Falls back to showing top 5 from the most recent completed tournament when no current tournament is available
- 🗓️ Automatically filters tournaments within a configurable date range (default: 7 days)
- 🔄 Configurable refresh interval (default: 10 minutes, adjustable up to 60 minutes)
- 🎨 User-configurable font size, font style, and colors
- ⭐ Highlights top 3 players with a different color (gold by default)
- 🚀 Uses ESPN's public API for real-time tournament data
- 💾 Built-in caching to minimize API requests

## Requirements

- LEDMatrix project (running on Raspberry Pi)
- Python 3.7+
- Internet connection for ESPN API access

## Installation

### 1. Clone this repository to your Raspberry Pi

```bash
# Navigate to a location outside the LEDMatrix project
cd ~
git clone <your-repo-url> ledmatrix-golf
```

### 2. Install the plugin in LEDMatrix

Option A: Using the web UI (recommended)
1. Open the LEDMatrix web interface at `http://your-pi:5000`
2. Navigate to the Plugins section
3. Click "Add Plugin Repository"
4. Enter the path: `/home/pi/ledmatrix-golf` (or wherever you cloned it)
5. Click "Load Plugin"

Option B: Manual installation
```bash
# Copy the plugin to the LEDMatrix plugins directory
cd /path/to/LEDMatrix
mkdir -p plugins/ledmatrix-golf
cp -r ~/ledmatrix-golf/* plugins/ledmatrix-golf/

# Or create a symbolic link
ln -s ~/ledmatrix-golf plugins/ledmatrix-golf
```

### 3. Install dependencies

The LEDMatrix system will automatically install dependencies from `requirements.txt` when loading the plugin.

If you need to install manually:
```bash
cd /path/to/LEDMatrix
pip3 install -r plugins/ledmatrix-golf/requirements.txt
```

### 4. Configure the plugin

Edit your LEDMatrix configuration (via web UI or `config.yaml`):

```yaml
plugins:
  pga-tour-leaderboard:
    enabled: true
    display_duration: 15
    update_interval: 600  # 10 minutes
    max_players: 10
    fallback_players: 5  # Players to show from previous tournament
    tournament_date_range: 7  # Look ahead 7 days
    font_size: 6
    font_name: "4x6-font.ttf"
    text_color:
      r: 255
      g: 255
      b: 255
    highlight_color:
      r: 255
      g: 215
      b: 0
```

### 5. Restart LEDMatrix

```bash
sudo systemctl restart ledmatrix
```

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `true` | Enable or disable the plugin |
| `display_duration` | number | `15` | How long to display the leaderboard (seconds) |
| `update_interval` | number | `600` | How often to refresh data from ESPN (seconds, 60-3600) |
| `max_players` | integer | `10` | Maximum number of players to display (1-20) |
| `fallback_players` | integer | `5` | Number of players from previous tournament to show as fallback (1-20) |
| `tournament_date_range` | integer | `7` | Number of days to look ahead for tournaments (0-30) |
| `font_size` | integer | `6` | Font size for text (4-12) |
| `font_name` | string | `"4x6-font.ttf"` | Font file to use (from assets/fonts) |
| `text_color` | object | `{r:255,g:255,b:255}` | RGB color for text (white) |
| `highlight_color` | object | `{r:255,g:215,b:0}` | RGB color for highlighting top 3 (gold) |

### Font Options

Available fonts (from LEDMatrix assets/fonts):
- `4x6-font.ttf` - Small, compact font (recommended for 64x32 displays)
- `PressStart2P-Regular.ttf` - Retro pixel font
- `tom-thumb.ttf` - Tiny font for maximum information density

### Color Customization

Colors are specified as RGB values (0-255):

```yaml
# White text
text_color:
  r: 255
  g: 255
  b: 255

# Gold highlight for leaders
highlight_color:
  r: 255
  g: 215
  b: 0

# Other color examples:
# Red: {r: 255, g: 0, b: 0}
# Green: {r: 0, g: 255, b: 0}
# Blue: {r: 0, g: 0, b: 255}
# Yellow: {r: 255, g: 255, b: 0}
```

## How It Works

1. **Data Fetching**: The plugin fetches PGA Tour leaderboard data from ESPN's public API
2. **Tournament Filtering**: It automatically filters to show only tournaments within your configured date range (e.g., today + 7 days)
3. **Fallback Mode**: If no current tournament is found, the plugin automatically searches for the most recent completed tournament (looks back up to 30 days) and displays the top finishers
4. **Leaderboard Display**: Shows player position, name, and score (e.g., "1. J.Smith -5")
   - When showing a previous tournament, the display shows "PREV:" before the tournament name
5. **Highlighting**: The top 3 players are displayed in the highlight color
6. **Caching**: API responses are cached to respect the update interval and minimize requests

## Display Format

**Current Tournament:**
```
Tournament Name
1. J.Smith -5
2. A.Jones -4
3. B.Lee -3
4. C.Park -2
5. D.Kim -1
6. E.Brown E
7. F.Davis +1
8. G.Miller +2
9. H.Wilson +3
10. I.Moore +4
```

**Previous Tournament (Fallback):**
```
PREV: Tournament Name
1. J.Smith -12
2. A.Jones -10
3. B.Lee -8
4. C.Park -7
5. D.Kim -6
```

## Troubleshooting

### Plugin not showing up
- Check that the plugin is enabled in the configuration
- Verify the plugin is loaded: Check the LEDMatrix logs at `/var/log/ledmatrix/ledmatrix.log`
- Ensure the manifest.json is valid JSON

### No tournament data displayed
- Check that there's a PGA Tour event within your configured date range
- Verify internet connectivity: `ping site.api.espn.com`
- Check the update interval - data may be cached
- View logs for API errors

### Display issues
- Try a smaller font size if text is cut off
- Adjust `max_players` if not all players fit on screen
- Check display dimensions match your LED matrix size

### Viewing logs

```bash
# View LEDMatrix logs
tail -f /var/log/ledmatrix/ledmatrix.log | grep pga-tour

# Or via journalctl
sudo journalctl -u ledmatrix -f | grep pga-tour
```

## ESPN API Information

This plugin uses ESPN's public API endpoint:
```
https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard
```

**Note**: This is an unofficial API. ESPN does not officially support or document this endpoint, and it may change without notice. For production use or guaranteed reliability, consider using an official golf API service like [SportsDataIO](https://sportsdata.io/) or [Sportradar](https://sportradar.com/).

## Development

### Project Structure

```
ledmatrix-golf/
├── manifest.json           # Plugin metadata and entry point
├── config_schema.json      # Configuration schema for web UI
├── manager.py             # Main plugin implementation
├── requirements.txt       # Python dependencies
├── README.md             # This file
└── plan.md               # Original requirements
```

### Testing

To test the plugin locally:

```python
# Test ESPN API connection
import requests
response = requests.get('https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard')
print(response.json())
```

### Contributing

1. Fork this repository
2. Create a feature branch
3. Make your changes
4. Test on your LED matrix
5. Submit a pull request

## License

This plugin is provided as-is for use with the LEDMatrix project. Please respect ESPN's terms of service when using their API.

## Credits

- Built for the [LEDMatrix project](https://github.com/ryderdamen/LEDMatrix)
- Data provided by ESPN's public API

## Support

For issues specific to this plugin, please open an issue in this repository.
For LEDMatrix issues, see the [LEDMatrix documentation](https://github.com/ryderdamen/LEDMatrix).

---

**Enjoy tracking your favorite PGA Tour players on your LED matrix! ⛳**
