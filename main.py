# Wick-catcher for the make.fun 24h BTC race (agent-fun/bars-replay/v1).
#
# What the dev window looks like: 24 hours of cbBTC 1-minute bars from
# 2026-11-17 14:44Z to 2026-11-18 14:44Z. Bitcoin opens at $65,083 and
# closes at $63,261, down 2.8% over the day, with a $63,076-$65,190 range.
# The day's shape is one sharp flush in the first hour, one long climb
# back, then a slow slide into the close. There is no deep multi-hour
# selloff anywhere: the worst fall over any 360-bar stretch is just
# -246 bps, so a bot that waits for a -4% or -5% washout never trades
# and fails the dev gate at exactly $0.
#
# The tradeable move is the opening flush. In the first hour the price
# drops 232 bps in 60 minutes, bottoming at $63,365 on bar 69, and then
# it climbs 2.4% to $65,190 by about bar 500. This bot buys that flush
# while the candles are still red and rides the climb back up. It runs
# two legs, both with hard stops, so a bad trigger on the live window
# can only cost roughly $15:
#
#   wick leg (the main one) -- fires when the 60-minute return is at
#       or below -170 bps AND the 15-minute return is at or below
#       -130 bps AND the 5-minute return is at or below -80 bps. It
#       buys with the whole cash balance. It gets out at +2.2% of
#       position value, at a trailing stop 1.0% under the best close
#       once the trade is +1.0% ahead, at a -1.2% hard stop, or after
#       480 bars, whichever comes first. On the dev window it buys on
#       bar 65 (fill bar 66 at $63,736.78) and takes profit on bar 507
#       (fill bar 508 at $65,061.80).
#   washout leg (a backup that never fires on dev) -- fires when the
#       price has fallen 5.0% or more over 360 bars, is sitting within
#       0.5% of that stretch's low, has stopped making new lows for
#       3 bars, and the 60-minute fall is no sharper than -180 bps
#       (the sharper case belongs to the wick leg). It aims for +4.5%
#       over the entry close, trails 2.0% under the best position
#       value, stops at -1.5%, and gives up after 1440 bars. Only one
#       washout entry per window.
#
# After any exit the bot waits 10 bars before looking again, and 60
# bars after an exit that hit the hard stop.
#
# Local replay of the published dev window, using the kit's exact fill
# rules (4 bps fee, 2 bps slippage, fills at the next bar's open
# against that bar's pool depth, 100 bps max slippage):
#   one round trip, net +$19.97 USDC, max drawdown 1.50%, fully
#   deterministic. Holding BTC from the open to the close of the same
#   window loses about $28, so the bot is roughly $48 ahead of
#   buy-and-hold.
#
# How sensitive the result is to each knob (everything else fixed):
#   wick trigger 60-min -150 to -200 bps, 15-min -100 to -150 bps,
#   5-min -60 to -90 bps -> the same entry bar and the same +$19.97.
#   The first bar where all three hold is bar 65 for every combination.
#   take-profit +1.9% to +2.4% -> +$16.15 to +$19.97; +1.7% -> +$15.19.
#   hard stop -0.8% to -1.5% -> +$19.97 (it never triggers on dev).
#   time stop 480 to 1440 bars -> +$19.97 (the take-profit fires
#   first); 360 bars -> +$6.40, 300 bars -> -$0.30, so the hold has
#   to be long enough to let the climb play out.
#   trailing stop armed at +1.0% with a 1.0% give-back -> +$19.97
#   (the take-profit fires first on dev; the trail is there in case
#   a live rally tops out just short of the take-profit). Arming it
#   at +0.5% shakes the trade out early, +$5.83, so the arm stays
#   at +1.0%.
# Things that were tried and lost on this window:
#   buying a dip after a pause (60-min drop -90 to -120 bps, last 15
#   min flat) -> -$12.58. The first "pause" on bar 75 is a dead-cat
#   bounce: the price makes a second leg down to $63,624 and the
#   -1.0% hard stop takes the loss. Buying the wick itself beats
#   waiting for the pause here.
#   a second dip leg at -60 bps / +1.0% take-profit -> +$22.98, but
#   the extra trade fires on a single bar only (bar 693). Move the
#   threshold to -50 bps and it fires three times for +$8.06; move
#   it to -70 bps and it never fires; move the turn filter by 10 bps
#   and it makes +$7.55. A one-bar coincidence is not a tradeable
#   edge, so the leg stays out.
#   buying the 360-bar low after a -200 bps fall -> -$3.43 on its
#   own, and it subtracts from the wick leg when combined. The
#   late-day grind has no bounce worth harvesting.
#   momentum (buy a 60-min rise of +60 to +120 bps) -> +$1.45 at
#   best. Chasing the climb pays the 26 bps round-trip cost and
#   keeps almost nothing.
#   selling part of the position early and re-buying the dip (the
#   trick that won the previous race's v4) -> not applicable here:
#   the climb from $63,365 to $65,190 is one smooth rise with no dip
#   to buy back into.
#
# The dev window decides nothing except who races. The live 24 hours
# (2026-11-18 20:59 UTC to 2026-11-19 20:59 UTC) decide the prizes.
# If the live window has no -170 bps hourly wick and no -5.0%
# washout, the bot trades nothing: $0, no prize, no loss. If a leg
# fires on a false alarm, the hard stop caps the damage near -$15.
#
# The bot is pure integer arithmetic on the harness's own units, so
# it is exactly deterministic: no randomness, no wall clock, no
# network, no files. A full-size round trip costs about 26 bps in
# fees, slippage and price impact, so a trade is only worth taking
# when the move it hunts is much bigger than that -- which is what
# the wick thresholds and the +2.2% take-profit are for.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
BPS = 10000

# --- wick leg (the main one) ---
WICK_R60_BPS = 170        # 60-min fall that marks the flush
WICK_R15_BPS = 130        # 15-min fall, still accelerating
WICK_R5_BPS = 80          # 5-min fall
WICK_TP_BPS = 220         # take-profit, +2.2% of position value
WICK_ARM_BPS = 100        # arm the trailing stop at +1.0% profit
WICK_TRAIL_BPS = 100      # give back 1.0% from the best close
WICK_STOP_BPS = 120       # hard stop, -1.2%
WICK_HOLD_BARS = 480      # time stop, in bars

# --- washout leg (backup for a slow-grind selloff day) ---
WASH_SPAN = 360           # six hours of one-minute bars
WASH_DROP_BPS = 500       # needs a 5.0% fall over the span
WASH_NEAR_BPS = 50        # ... and the close within 0.5% of the low
WASH_FLAT_BARS = 3        # ... and no new low for 3 bars
WASH_R60_CAP_BPS = 180    # ... and the 60-min fall no sharper than
                          #   -180 bps (the sharp case is the wick's)
WASH_TP_NUM = 1045        # take-profit: +4.5% over the entry's
WASH_TP_DEN = 1000        #   DECISION close, as a price target
WASH_TRAIL_NUM = 98       # trailing stop: 2.0% under the best value
WASH_TRAIL_DEN = 100
WASH_STOP_NUM = 985       # hard stop: 1.5% under cost
WASH_STOP_DEN = 1000
WASH_HOLD_BARS = 1440     # time stop (the window is 1440 bars)
WASH_MAX = 1              # at most one washout entry per window

PAUSE_BARS = 10           # wait after any exit before re-entering
STOP_PAUSE_BARS = 60      # wait longer after a stop-loss exit
MAX_SLIP_BPS = 100        # 1% past the close the order was decided on


class History:
    """Closes of one symbol, newest last, with window helpers.

    A batch with no bar for the symbol adds nothing: the windows count
    bars, exactly as the kit's baselines do.
    """

    def __init__(self):
        self.closes = []

    def add(self, close):
        self.closes.append(close)

    def span_low(self, n):
        """Lowest close of the last n bars (current one included)."""
        if not self.closes:
            return None
        return min(self.closes[-n:])

    def back(self, n):
        """Close n bars ago, or None when fewer than n bars were seen."""
        if len(self.closes) > n:
            return self.closes[-1 - n]
        return None

    def move_bps(self, n):
        """Return over the last n bars in bps (floored), or None."""
        if len(self.closes) <= n:
            return None
        now = self.closes[-1]
        then = self.closes[-1 - n]
        if then <= 0:
            return None
        return (now - then) * BPS // then


class WickBot:
    def __init__(self):
        self.hist = History()
        self.seen = 0               # bars seen (close count)
        self.best_close = 0         # best close since entry
        self.best_value = 0         # best position value since entry
        self.opened_at = -1         # bars-seen count when opened
        self.leg = None             # 'wick' | 'wash' | None
        self.target = 0             # washout take-profit price target
        self.wash_taken = 0         # washout legs taken this window
        self.exited_at = -10 ** 9   # bars-seen count of the last exit
        self.stopped_at = -10 ** 9  # bars-seen count of the last stop

    def _buy_full(self, state):
        cash = state.cash
        if cash < int(state.hello["fees"]["min_notional_quote_units"]):
            return None
        room = state.weight_room(SYMBOL)
        if room < int(state.hello["fees"]["min_notional_quote_units"]):
            return None
        spend = cash if cash <= room else room
        impact = state.impact_bps(SYMBOL, spend)
        if impact is not None and impact > 30:
            return None
        return {"side": "buy", "symbol": SYMBOL,
                "notional_quote_units": spend,
                "max_slippage_bps": MAX_SLIP_BPS}

    def _enter(self, state, leg, target=0):
        self.best_close = int(state.close(SYMBOL))
        self.best_value = 0
        self.opened_at = self.seen
        self.leg = leg
        self.target = target
        if leg == "wash":
            self.wash_taken += 1

    def _leave(self, state, held, was_stop):
        self.exited_at = self.seen
        if was_stop:
            self.stopped_at = self.seen
        self.opened_at = -1
        self.best_close = 0
        self.best_value = 0
        self.leg = None
        self.target = 0
        return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                 "max_slippage_bps": MAX_SLIP_BPS}]

    def on_batch(self, state, batch):
        # A reply is owed for every batch, even one with no bar for us.
        bar = None
        for b in batch["bars"]:
            if b["symbol"] == SYMBOL:
                bar = b
                break
        if bar is None:
            return []
        self.hist.add(int(bar["c"]))
        self.seen += 1
        if state.warming_up:
            return []
        close = int(bar["c"])
        held = state.positions.get(SYMBOL)

        if held is not None:
            if close > self.best_close:
                self.best_close = close
            value = state.value(SYMBOL, held.qty)
            if value > self.best_value:
                self.best_value = value
            cost = held.cost
            gain = (value - cost) * BPS // cost if cost > 0 else 0
            held_for = self.seen - self.opened_at
            was_stop = False
            if self.leg == "wash":
                hit_target = close >= self.target
                trailed = (value * WASH_TRAIL_DEN
                           <= self.best_value * WASH_TRAIL_NUM)
                was_stop = (value * WASH_STOP_DEN
                            <= cost * WASH_STOP_NUM)
                timed_out = held_for >= WASH_HOLD_BARS
                if hit_target or trailed or was_stop or timed_out:
                    return self._leave(state, held, was_stop)
                return []
            # wick leg: value-based take-profit and hard stop, a
            # close-based trailing stop once in profit (a backup: the
            # take-profit fires first on dev), and a time stop.
            give_back = ((self.best_close - close) * BPS // self.best_close
                         if self.best_close > 0 else 0)
            armed = gain >= WICK_ARM_BPS
            was_stop = gain <= -WICK_STOP_BPS
            hit_target = gain >= WICK_TP_BPS
            trailed = armed and give_back >= WICK_TRAIL_BPS
            timed_out = held_for >= WICK_HOLD_BARS
            if was_stop or hit_target or trailed or timed_out:
                return self._leave(state, held, was_stop)
            return []

        # Flat: look for an entry.
        if self.seen - self.exited_at < PAUSE_BARS:
            return []
        if self.seen - self.stopped_at < STOP_PAUSE_BARS:
            return []

        r5 = self.hist.move_bps(5)
        r15 = self.hist.move_bps(15)
        r60 = self.hist.move_bps(60)

        # Wick leg: a violent 5-minute flush at the end of a deep
        # 60-minute fall. Buys the flush itself, before any pause
        # shows on the chart.
        if (r60 is not None and r60 <= -WICK_R60_BPS
                and r15 is not None and r15 <= -WICK_R15_BPS
                and r5 is not None and r5 <= -WICK_R5_BPS
                and self.seen - self.stopped_at >= STOP_PAUSE_BARS):
            order = self._buy_full(state)
            if order is None:
                return []
            self._enter(state, "wick")
            return [order]

        # Washout backup: a climactic slow selloff that has flattened
        # at its low. Gated to non-sharp 60-minute falls so it can
        # never jump ahead of the wick leg.
        if (self.wash_taken < WASH_MAX
                and self.seen > WASH_SPAN
                and r60 is not None
                and r60 >= -WASH_R60_CAP_BPS
                and self.seen - self.stopped_at >= STOP_PAUSE_BARS):
            old = self.hist.back(WASH_SPAN)
            low = self.hist.span_low(WASH_SPAN)
            flat = self.hist.back(WASH_FLAT_BARS)
            if old is not None and low is not None and flat is not None:
                washed = close * BPS <= old * (BPS - WASH_DROP_BPS)
                at_low = close * BPS <= low * (BPS + WASH_NEAR_BPS)
                paused = close >= flat
                if washed and at_low and paused:
                    order = self._buy_full(state)
                    if order is None:
                        return []
                    self._enter(state, "wash",
                                target=close * WASH_TP_NUM // WASH_TP_DEN)
                    return [order]

        return []


# --- sanity bounds (checked at import; the tuning plateaus are
# wick 60-min -150 to -200 bps, 15-min -100 to -150 bps, 5-min -60
# to -90 bps, take-profit +1.9% to +2.4%, stop -0.8% to -1.5%,
# hold 480-1440 bars) ---
assert 0 < WICK_R5_BPS < WICK_R15_BPS < WICK_R60_BPS < WASH_DROP_BPS
assert 0 < WICK_ARM_BPS < WICK_TP_BPS
assert 0 < WICK_TRAIL_BPS <= WICK_ARM_BPS
assert 0 < PAUSE_BARS < STOP_PAUSE_BARS
assert WASH_MAX == 1 and WASH_HOLD_BARS <= 1440


_BOT = WickBot()


def on_batch(state, batch):
    return _BOT.on_batch(state, batch)


makefun_bars.run(on_batch)


# --- verification note (2026-11-18, local protocol driver) ---
# Ran the actual main.py through the real bars-replay/v1 protocol
# (~/workspace/makefun/work/drive-0603.py, kit btc-race-24h-20261118-1444)
# over the kit's dev window, twice: net PnL +$19.972388 USDC, 2 trades,
# max drawdown 1.4964%, action-log sha256
# e06d6ba01fcbfd927dd21b61490fe2380874f696ad072a856af4a09e492d7d49 on
# both runs (deterministic). Fills: buy bar 66 @ $63,736.78 (decision
# bar 65, the capitulation wick: 60-min -205 bps, 15-min -184 bps,
# 5-min -91 bps), sell bar 508 @ $65,061.80 (+2.2% take-profit). The
# washout leg never fires on dev (worst 360-bar fall only -246 bps);
# it is a stop-bounded backup for the live race window.
