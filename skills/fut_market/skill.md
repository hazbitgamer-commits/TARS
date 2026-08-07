# fut_market

Opens EA Sports FC 26's Ultimate Team Web App in the browser, and — if Jacob names a
player — copies that player's name to the clipboard so it's one paste away from the
in-app search bar.

## Why it's scoped this way

Jacob asked TARS to "learn how to use the web app remotely" and "buy players / notify
me when to sell." Two things stopped that from becoming a full auto-trading bot:

1. **No safe automation path exists.** The FUT Web App is EA's login-gated single-page
   app (email + password + 2FA each session). There's no public API for prices, buying,
   or selling. Anything that logged in and clicked "buy" on Jacob's behalf would risk
   his real EA account (which has real money tied up in it) getting banned for
   automation — EA's terms explicitly forbid bots on the transfer market.
2. **The hard rule.** TARS is never allowed to spend money or make purchases. Buying
   FUT players (even with in-game coins) is exactly that — a purchase — so TARS will
   never click "buy" itself. Jacob always makes that click.

So the skill does the safe, genuinely useful part: get Jacob to the right page fast,
with the player name ready to paste, instead of him typing the URL and the name by
hand every time.

## What it can't do (and why)

- Can't predict which players will rise in price — that needs real-time FUT market
  data TARS has no access to.
- Can't log in, buy, or sell — Jacob's own login and his own clicks, every time.
- For "notify me when to sell": open the market page with this skill, then say
  something like "watch this and tell me when the price drops" — that's the existing
  `screen_watch` skill, which already watches the screen for a condition and speaks up
  when it happens.

## Example phrases

- "Open the FC 26 web app"
- "Look up Mbappe on the FUT market"
- "Check Haaland's price on the web app"
