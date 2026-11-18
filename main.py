# Capitulation-wick bot for the make.fun BTC 24h race (agent-fun/bars-replay/v1).
#
# The dev window (2026-11-17 14:44Z to 2026-11-18 14:44Z) is a grind-down
# day: BTC opens $65,083, closes $63,261 (-2.8%), range $63,076-$65,190.
# There is NO washout on it -- the worst 360-bar fall is only -246 bps --
# so the deep-dip / washout legs that won the earlier races (which needed
# -270 to -500 bps moves) can never fire here. The window's one big move
# is a capitulation wick in the first hour: the price falls -232 bps in
# 60 minutes to $63,365 at bar 69, then recovers +2.4% to $65,190 by
# bar ~500, then grinds down for the rest of the day.
#
# This bot therefore buys the wick itself, while it is still falling, and
# rides the recovery. Two legs, both stop-bounded:
#
#   spike leg (primary) -- a violent wick: 60-min return <= -170 bps AND
#       15-min return <= -130 bps AND 5-min return <= -80 bps. Buys the
#       wick at full size. Exits at +2.2% take-profit, a 1.0% trailing
#       stop below the peak close (armed at +1.0%), a -1.2% hard stop,
#       or a 480-bar time stop. On dev it buys bar 65 @ $63,737 (fill)
#       and sells at +2.2% @ $65,062.
#   washout leg (backup, never fires on dev) -- a -5.0% fall over 360
#       bars, the close within 0.5% of the 360-bar low, paused 3 bars,
#       and the 60-min fall NOT sharper than -180 bps (the sharp case
#       is the spike leg's). Exits: +4.5% price-target take-profit,
#       2.0% trailing stop on value, -1.5% hard stop, 1440-bar hold.
#       At most one washout entry per window.
#
# Cooldown: 10 bars after any exit, 60 bars after a stop-loss exit.
# Every leg is stop-bounded, so a false fire on the race window costs
# at most about -$15 per leg.
#
# Measured on the published dev window with an exact local replay of
# the harness (fee 4 bps, slippage 2 bps, fill at the next bar's open
# against the pool depth, max slippage 100 bps):
#   spike: buy bar 65 @ $63,736.78, sell bar ~507 @ $65,061.80
#   net PnL +$19.97 USDC, 2 trades, max drawdown 1.50%, deterministic.
#   Buy-and-hold on the same window loses about -$28, so the bot beats
#   it by roughly $48.
#
# Robustness (one parameter varied at a time, all else at the base):
#   spike dip 150-200 bps, turn 100-150 bps, 5-min -60 to -90 bps ->
#   the SAME entry bar and the SAME +$19.97 (the wick's first bar that
#   meets all three is bar 65 for every combination).
#   spike TP 190-240 bps -> +$16.15-19.97; TP 170 -> +$15.19.
#   spike stop -0.8% to -1.5% -> +$19.97 (never triggers on dev).
#   spike hold 480-1440 bars -> +$19.97 (the TP fires first);
#   hold 360 -> +$6.40, hold 300 -> -$0.30 (the time stop cuts the
#   rally short, so the hold must be long).
#   trailing stop armed at +1.0% / 1.0% below peak -> +$19.97
#   (the TP fires first on dev; the trail only protects a rally that
#   tops just below the TP on the race window). Arm at +0.5% shakes
#   the trade out early (+$5.83), so the arm must be +1.0% or more.
# Rejected on this window (all tested, all worse):
#   dip-with-pause (60-min drop -90 to -120 bps, last 15 min flat) ->
#   -$12.58: the first "pause" at bar 75 is a dead-cat bounce before
#   a second leg down to $63,624, and the -1.0% hard stop takes the
#   loss. Buying the wick beats waiting for the pause here.
#   dip 60 bps + TP 1.0% as a second leg -> +$22.98, but the extra
#   trade fires on ONE bar only (bar 693, 60-min -62 bps, 15-min +7
#   bps): dip 50 -> +$8.06, dip 70 -> never fires, turn -10 -> +$7.55.
#   A one-bar coincidence, not a plateau: rejected as overfit.
#   range leg (360-bar low after a -200 bps fall) -> -$3.43 alone,
#   and it subtracts from the spike leg when combined: the late-day
#   grind has no bounce to harvest.
#   momentum breakout (60-min rise >= +60-120 bps) -> +$1.45 at best:
#   chasing the rally loses to the round-trip cost.
#   partial exit (sell 4/5 at +1.2%, re-buy on the dip, as in the
#   previous race's v4) -> not applicable: the rally here is one
#   smooth rise to $65,190 with no dip to re-buy into.
#
# Caveat: the dev window does not decide the prizes. The live 24h
# race window (2026-11-18 20:59 UTC to 2026-11-19 20:59 UTC) does.
# If that window has no -170 bps hourly wick and no -5.0% washout,
# the bot trades nothing (PnL 0, no prize, no loss). If a leg fires
# falsely, its hard stop bounds the loss to about -$15.
#
# Everything is integer arithmetic on the harness's own units, so the
# bot is exactly deterministic: no randomness, no wall clock, no
# network, no files. A full-size round trip costs about 26 bps in
# fees, slippage and impact, so a trade only makes sense when the
# expected move is far larger than that -- which is what the wick
# thresholds and the +2.2% take-profit are for.

import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
BPS = 10000

# --- spike leg (primary) ---
SPIKE_DIP_BPS = 170       # 60-min drop
SPIKE_TURN_BPS = 130      # 15-min drop still accelerating (negative)
SPIKE_R5_BPS = 80         # 5-min drop
SPIKE_TP_BPS = 220        # take-profit +2.2%
SPIKE_ARM_BPS = 100       # arm the trailing stop once +1.0% in profit
SPIKE_TRAIL_BPS = 100     # exit 1.0% below the peak close
SPIKE_STOP_BPS = 120      # hard stop -1.2%
SPIKE_HOLD_BARS = 480     # time stop, in bars

# --- washout leg (backup: slow-grind selloff) ---
WASH_LOOKBACK = 360       # six hours of one-minute bars
WASH_DROP_BPS = 500       # entry needs a 5.0% fall over the lookback
WASH_NEAR_BPS = 50        # ... and the close within 0.5% of the low
WASH_STAB_BARS = 3        # ... and the close no lower than 3 bars ago
WASH_GATE60_BPS = 180     # ... and the 60-min fall NOT sharper than -180
                          #   bps (the sharp case is the spike leg's)
WASH_TP_NUM = 1045        # washout take-profit: +4.5% over the entry's
WASH_TP_DEN = 1000        #   DECISION close (a price target)
WASH_TRAIL_NUM = 98       # washout trailing stop: 2.0% below peak value
WASH_TRAIL_DEN = 100
WASH_STOP_NUM = 985       # washout hard stop: 1.5% below cost
WASH_STOP_DEN = 1000
WASH_HOLD_BARS = 1440     # washout time stop (the window is 1440 bars)
WASH_MAX_ENTRIES = 1      # at most one washout leg per window

COOLDOWN_BARS = 10
STOP_COOLDOWN_BARS = 60   # after a stop-loss exit, wait longer
MAX_SLIPPAGE_BPS = 100    # 1% past the close the order was decided on


class Series:
    """The closes of one symbol, with a rolling minimum over 360 bars.

    A gap (a batch with no bar for the symbol) adds nothing: the windows
    count bars, exactly as the kit's baselines do.
    """

    def __init__(self):
        self.closes = []            # closes, oldest first, as ints
        self._min_q = deque()       # (index, close) with rising closes

    def push(self, close):
        idx = len(self.closes)
        self.closes.append(close)
        while self._min_q and self._min_q[-1][1] >= close:
            self._min_q.pop()
        self._min_q.append((idx, close))
        while self._min_q and self._min_q[0][0] <= idx - WASH_LOOKBACK:
            self._min_q.popleft()
        if len(self.closes) > 400:
            self.closes.pop(0)
            # indices in _min_q shift by one after the pop
            self._min_q = deque((i - 1, c) for i, c in self._min_q)

    def low360(self):
        """The lowest close of the last 360 bars (current one included)."""
        return self._min_q[0][1] if self._min_q else None

    def ago(self, n):
        """The close n bars ago, or None when fewer than n bars were seen."""
        if len(self.closes) > n:
            return self.closes[-1 - n]
        return None

    def ret_bps(self, n):
        """The return over the last n bars in bps (floored), or None."""
        if len(self.closes) <= n:
            return None
        now = self.closes[-1]
        then = self.closes[-1 - n]
        if then <= 0:
            return None
        return (now - then) * BPS // then


class Bot:
    def __init__(self):
        self.series = Series()
        self.n = 0                  # bars seen (close count)
        self.peak_close = 0         # highest close seen since entry
        self.peak_value = 0         # highest position value since entry
        self.entry_bar = -1         # bars-seen count when opened
        self.leg = None             # 'spike' | 'wash' | None
        self.tp_price = 0           # washout take-profit price target
        self.wash_entries = 0       # washout legs taken this window
        self.last_exit = -10 ** 9   # bars-seen count of the last exit
        self.last_stop = -10 ** 9   # bars-seen count of the last stop

    def _buy_all(self, state):
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
                "max_slippage_bps": MAX_SLIPPAGE_BPS}

    def _open(self, state, leg, tp_price=0):
        self.peak_close = int(state.close(SYMBOL))
        self.peak_value = 0
        self.entry_bar = self.n
        self.leg = leg
        self.tp_price = tp_price
        if leg == "wash":
            self.wash_entries += 1

    def _exit(self, state, held, stop_loss):
        self.last_exit = self.n
        if stop_loss:
            self.last_stop = self.n
        self.entry_bar = -1
        self.peak_close = 0
        self.peak_value = 0
        self.leg = None
        self.tp_price = 0
        return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    def on_batch(self, state, batch):
        # A reply is owed for every batch, even one with no bar for us.
        bar = None
        for b in batch["bars"]:
            if b["symbol"] == SYMBOL:
                bar = b
                break
        if bar is None:
            return []
        self.series.push(int(bar["c"]))
        self.n += 1
        if state.warming_up:
            return []
        close = int(bar["c"])
        held = state.positions.get(SYMBOL)

        if held is not None:
            if close > self.peak_close:
                self.peak_close = close
            value = state.value(SYMBOL, held.qty)
            if value > self.peak_value:
                self.peak_value = value
            cost = held.cost
            gain = (value - cost) * BPS // cost if cost > 0 else 0
            held_bars = self.n - self.entry_bar
            stop_loss = False
            if self.leg == "wash":
                take_profit = close >= self.tp_price
                trailing = (value * WASH_TRAIL_DEN
                            <= self.peak_value * WASH_TRAIL_NUM)
                stop_loss = (value * WASH_STOP_DEN
                             <= cost * WASH_STOP_NUM)
                time_stop = held_bars >= WASH_HOLD_BARS
                if take_profit or trailing or stop_loss or time_stop:
                    return self._exit(state, held, stop_loss)
                return []
            # spike leg: value-based take-profit and hard stop, close-based
            # trailing stop once in profit (a backup: the TP fires first
            # on dev), time stop.
            peak_drop = ((self.peak_close - close) * BPS // self.peak_close
                         if self.peak_close > 0 else 0)
            armed = gain >= SPIKE_ARM_BPS
            stop_loss = gain <= -SPIKE_STOP_BPS
            take_profit = gain >= SPIKE_TP_BPS
            trailing = armed and peak_drop >= SPIKE_TRAIL_BPS
            time_stop = held_bars >= SPIKE_HOLD_BARS
            if stop_loss or take_profit or trailing or time_stop:
                return self._exit(state, held, stop_loss)
            return []

        # Flat: look for an entry.
        if self.n - self.last_exit < COOLDOWN_BARS:
            return []
        if self.n - self.last_stop < STOP_COOLDOWN_BARS:
            return []

        ret5 = self.series.ret_bps(5)
        ret15 = self.series.ret_bps(15)
        ret60 = self.series.ret_bps(60)

        # Spike leg: a violent 5-minute wick at the end of a deep
        # 60-min fall. Buys the wick itself, before any pause is visible.
        if (ret60 is not None and ret60 <= -SPIKE_DIP_BPS
                and ret15 is not None and ret15 <= -SPIKE_TURN_BPS
                and ret5 is not None and ret5 <= -SPIKE_R5_BPS
                and self.n - self.last_stop >= STOP_COOLDOWN_BARS):
            order = self._buy_all(state)
            if order is None:
                return []
            self._open(state, "spike")
            return [order]

        # Washout backup entry: a climactic slow selloff that has paused
        # at its low. Gated to non-sharp 60-min falls so it can never
        # pre-empt the spike leg.
        if (self.wash_entries < WASH_MAX_ENTRIES
                and self.n > WASH_LOOKBACK
                and ret60 is not None
                and ret60 >= -WASH_GATE60_BPS
                and self.n - self.last_stop >= STOP_COOLDOWN_BARS):
            old = self.series.ago(WASH_LOOKBACK)
            low = self.series.low360()
            stab = self.series.ago(WASH_STAB_BARS)
            if old is not None and low is not None and stab is not None:
                washed_out = close * BPS <= old * (BPS - WASH_DROP_BPS)
                near_low = close * BPS <= low * (BPS + WASH_NEAR_BPS)
                paused = close >= stab
                if washed_out and near_low and paused:
                    order = self._buy_all(state)
                    if order is None:
                        return []
                    self._open(state, "wash",
                               tp_price=close * WASH_TP_NUM // WASH_TP_DEN)
                    return [order]

        return []


# --- parameter sanity (checked at import; the tuner plateaus are
# spike dip 150-200 bps, turn 100-150 bps, 5-min -60 to -90 bps,
# TP 190-240 bps, stop -0.8% to -1.5%, hold 480-1440 bars) ---
assert 0 < SPIKE_R5_BPS < SPIKE_TURN_BPS < SPIKE_DIP_BPS < WASH_DROP_BPS
assert 0 < SPIKE_ARM_BPS < SPIKE_TP_BPS
assert 0 < SPIKE_TRAIL_BPS <= SPIKE_ARM_BPS
assert 0 < COOLDOWN_BARS < STOP_COOLDOWN_BARS
assert WASH_MAX_ENTRIES == 1 and WASH_HOLD_BARS <= 1440


_BOT = Bot()


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
