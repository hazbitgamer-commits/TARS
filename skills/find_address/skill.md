# find_address

Looks up the real-world street/postal address of a place, business, or
landmark by name, and speaks it back to Jacob.

Uses OpenStreetMap's free Nominatim geocoding service — the same one
`map_view` already uses internally to drop pins — so there's no API key
and no cost. This skill is different from `map_view`: it reads the
address out loud instead of drawing a marker on the dashboard map.

## Example phrases
- "Find the address of the Eiffel Tower"
- "What's the address of Woolworths Claremont"
- "Find the address for 10 Downing Street"

## Args
- `query`: the place, business, or landmark name to find the address for.

## Notes
- Read-only web lookup. No files are deleted, no money is spent, no
  messages are sent.
- If the lookup service is unreachable, or nothing matches, it says so
  plainly instead of guessing.
