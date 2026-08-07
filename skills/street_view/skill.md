# street_view
Opens a live Google Street View panel on the TARS dashboard, right over the
usual overhead map. Geocodes the place with OpenStreetMap (free, no key),
writes `street_view_state.json`, and the dashboard swaps the map card for
an embedded 360 photo (no API key needed — uses Google's key-less embed).

**Say:** "open street view on the dashboard" / "show me street view of the
Eiffel Tower" / "close street view"
**Args:** `action` ('show' or 'close'), `place` (address/place name, for 'show').

Not the same as `map_view` (the overhead pin map) or `browser_search`
(maps/directions in a browser tab) — this is specifically the street-level
photo panel on the dashboard.
