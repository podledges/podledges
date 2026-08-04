#!/usr/bin/env python3
"""README blackjack. Usage: blackjack.py init|deal|hit|stand [player]

State lives in game/state.json; renders assets/blackjack.svg plus the
state-aware button sprites btn_play.svg / btn_hit.svg / btn_stand.svg.
Cards come off a SystemRandom-shuffled deck — real randomness.

Economy: the table stakes you 200 gold, every hand is 100 flat,
blackjack pays 3:2. Go broke and the run ends — the quit screen shows
where you landed on the lifetime ledger; PLAY re-buys a fresh 200.
"""

import json
import os
import random
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
STATE = os.path.join(ROOT, "game", "state.json")
ASSETS = os.path.join(ROOT, "assets")
BET = 100
STAKE = 200
PLAYER = "anon"  # github login of whoever made the move; set in main()

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def new_deck():
    deck = [r + s for s in SUITS for r in RANKS]
    random.SystemRandom().shuffle(deck)
    return deck


def hand_value(hand):
    total, aces = 0, 0
    for card in hand:
        rank = card[:-1]
        if rank == "A":
            total, aces = total + 11, aces + 1
        elif rank in ("J", "Q", "K"):
            total += 10
        else:
            total += int(rank)
    while total > 21 and aces:
        total, aces = total - 10, aces - 1
    return total


def fresh_state():
    return {
        "phase": "idle",  # idle | player | done | broke
        "deck": [], "player": [], "dealer": [],
        "msg": "table open — press play",
        "balance": STAKE,
        "session": {"hands": 0, "peak": STAKE, "players": {}},
        "ledger": {"best": [], "worst": []},
        "stats": {"games": 0, "pnl": 0, "last": []},
    }


def migrate(s):
    base = fresh_state()
    for k, v in base.items():
        s.setdefault(k, v)
    for k, v in base["stats"].items():
        s["stats"].setdefault(k, v)
    s["session"].setdefault("players", {})
    led = s["ledger"]
    if not isinstance(led.get("best"), list):  # pre-highscore ledger shape
        led["best"] = [led["best"]] if led.get("best") else []
    for e in led["best"] + led["worst"]:
        e.setdefault("by", "anon")
    return s


def load():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return migrate(json.load(f))
    return fresh_state()


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)


def end_session(s):
    """Run went broke — file it on the lifetime ledger."""
    players = s["session"].get("players", {})
    entry = {
        "hands": s["session"]["hands"],
        "peak_net": s["session"]["peak"] - STAKE,
        "final": s["balance"] - STAKE,
        "by": max(players, key=players.get) if players else PLAYER,
    }
    led = s["ledger"]
    led["best"] = sorted(led["best"] + [entry],
                         key=lambda e: (-e["peak_net"], e["hands"]))[:3]
    led["worst"] = sorted(led["worst"] + [entry],
                          key=lambda e: (e["hands"], e["peak_net"]))[:3]


def settle(s, result, delta, msg):
    """result: 'W' | 'L' | 'P'"""
    s["balance"] += delta
    s["stats"]["games"] += 1
    s["stats"]["pnl"] += delta
    s["stats"]["last"] = (s["stats"]["last"] + [result])[-10:]
    s["session"]["hands"] += 1
    pl = s["session"].setdefault("players", {})
    pl[PLAYER] = pl.get(PLAYER, 0) + 1
    s["session"]["peak"] = max(s["session"]["peak"], s["balance"])
    sign = "+" if delta > 0 else ""
    tail = f" ({sign}{delta} gold)" if delta else " (push)"
    if s["balance"] < BET:
        s["phase"] = "broke"
        end_session(s)
        s["msg"] = f"{msg}{tail} — out of gold."
    else:
        s["phase"] = "done"
        s["msg"] = f"{msg}{tail}"


def act(s, move):
    if move == "deal":
        if s["phase"] == "player":
            # abandoning a live hand counts as a loss — no rage-quitting
            settle(s, "L", -BET, "hand abandoned")
            if s["phase"] == "broke":
                return
        if s["phase"] == "broke":
            s["balance"] = STAKE
            s["session"] = {"hands": 0, "peak": STAKE, "players": {}}
        s.update(deck=new_deck(), player=[], dealer=[], phase="player")
        s["player"] = [s["deck"].pop(), s["deck"].pop()]
        s["dealer"] = [s["deck"].pop(), s["deck"].pop()]
        pv, dv = hand_value(s["player"]), hand_value(s["dealer"])
        if pv == 21 and dv == 21:
            settle(s, "P", 0, "double blackjack — push")
        elif pv == 21:
            settle(s, "W", int(BET * 1.5), "blackjack!")
        elif dv == 21:
            settle(s, "L", -BET, "podles has blackjack")
        else:
            s["msg"] = f"you show {pv}. hit or stand?"
        return

    if s["phase"] != "player":
        s["msg"] = "no live hand — press play."
        return

    if move == "hit":
        s["player"].append(s["deck"].pop())
        pv = hand_value(s["player"])
        if pv > 21:
            settle(s, "L", -BET, f"bust at {pv}")
        elif pv == 21:
            act(s, "stand")
        else:
            s["msg"] = f"drew {s['player'][-1]} — {pv}. hit or stand?"
    elif move == "stand":
        while hand_value(s["dealer"]) < 17:
            s["dealer"].append(s["deck"].pop())
        pv, dv = hand_value(s["player"]), hand_value(s["dealer"])
        if dv > 21:
            settle(s, "W", BET, f"podles busts at {dv}")
        elif pv > dv:
            settle(s, "W", BET, f"{pv} beats {dv}")
        elif pv < dv:
            settle(s, "L", -BET, f"{dv} beats {pv}")
        else:
            settle(s, "P", 0, f"push at {pv}")


# ── palette ──────────────────────────────────────────────────────────────
BG = "#0a0e14"
PANEL = "#0e141c"
BORDER = "#1c2733"
DIM = "#46586a"
TEXT = "#93a7b8"
BRIGHT = "#e8f1f8"
BLUE = "#7fd0f5"
PINK = "#ff54a8"
AMBER = "#f5b043"
LIME = "#ccff5e"
GOLD = "#f5c95c"
GOLD_DARK = "#a97e22"
MONO = "ui-monospace,'JetBrains Mono','Cascadia Code',Consolas,monospace"

CARD_W, CARD_H = 46, 62
DECK_X, DECK_Y = 606, 60  # where cards fly in from


# pixel-art podle coin: '#' outline, 'y' gold, 'd' dark (ring/P), 'h' shine, 'g' shade
COIN_PIX = [
    "....####....",
    "..##yyyy##..",
    ".#hyyyyyyg#.",
    ".#hyydddyg#.",
    "#yhyydydyyg#",
    "#yhyydddyyg#",
    "#yhyydyyyyg#",
    ".#hyydyyyg#.",
    ".#hyyyyyyg#.",
    "..##gggg##..",
    "....####....",
]
COIN_COLS = {"#": "#161006", "y": GOLD, "d": GOLD_DARK, "h": "#ffe9a8", "g": "#c9992e"}


def pixel_coin(x, y, size=16.0):
    """Pixel-art gold coin with a P, top-left corner at (x, y)."""
    px_size = size / 12
    out = ['<g shape-rendering="crispEdges">']
    for r, row in enumerate(COIN_PIX):
        for c, ch in enumerate(row):
            if ch == ".":
                continue
            out.append(
                f'<rect x="{x + c * px_size:.2f}" y="{y + r * px_size:.2f}" '
                f'width="{px_size:.2f}" height="{px_size:.2f}" fill="{COIN_COLS[ch]}"/>'
            )
    out.append("</g>")
    return "".join(out)


def card_face(card, hidden):
    """Card artwork at local origin (0,0)."""
    if hidden:
        # unfaced card: inset frame + diagonal weave + center pip
        return (
            f'<rect width="{CARD_W}" height="{CARD_H}" rx="5" fill="{PANEL}" stroke="{DIM}"/>'
            f'<rect x="4" y="4" width="{CARD_W - 8}" height="{CARD_H - 8}" rx="3" '
            f'fill="none" stroke="{DIM}" stroke-opacity="0.7"/>'
            f'<path d="M6,14 L18,6 M6,26 L30,6 M6,38 L40,14 M6,50 L40,26 M12,56 L40,38 '
            f'M24,56 L40,50" stroke="{DIM}" stroke-opacity="0.45" stroke-width="1"/>'
            f'<rect x="17" y="25" width="12" height="12" transform="rotate(45 23 31)" '
            f'fill="none" stroke="{PINK}" stroke-opacity="0.8"/>'
            f'<text x="23" y="34.5" font-size="9" text-anchor="middle" fill="{PINK}" '
            f'fill-opacity="0.9" font-weight="bold">?</text>'
        )
    rank, suit = card[:-1], card[-1]
    color = PINK if suit in "♥♦" else BRIGHT
    return (
        f'<rect width="{CARD_W}" height="{CARD_H}" rx="5" fill="{PANEL}" stroke="{BORDER}"/>'
        f'<text x="7" y="17" font-size="13" fill="{color}">{rank}</text>'
        f'<text x="{CARD_W / 2}" y="{CARD_H / 2 + 10}" font-size="17" '
        f'text-anchor="middle" fill="{color}">{suit}</text>'
        f'<text x="{CARD_W - 7}" y="{CARD_H - 8}" font-size="13" '
        f'text-anchor="end" fill="{color}">{rank}</text>'
    )


def dealt_card(x, y, card, delay, hidden=False):
    """Card that flies in from the deck with a staggered delay."""
    dx, dy = DECK_X - x, DECK_Y - y
    return (
        f'<g transform="translate({x},{y})"><g opacity="0">'
        f'<animate attributeName="opacity" to="1" begin="{delay:.2f}s" dur="0.2s" fill="freeze"/>'
        f'<animateTransform attributeName="transform" type="translate" '
        f'from="{dx} {dy}" to="0 0" begin="{delay:.2f}s" dur="0.4s" fill="freeze" '
        f'calcMode="spline" keySplines="0.2 0.8 0.2 1"/>'
        f'{card_face(card, hidden)}</g></g>'
    )


def msg_markup(s):
    msg = s["msg"]
    if msg.endswith("hit or stand?"):
        head = msg[: -len("hit or stand?")]
        return (
            f'{head}<tspan fill="{BLUE}" font-weight="bold">hit</tspan>'
            f'<tspan fill="{TEXT}"> or </tspan>'
            f'<tspan fill="{PINK}" font-weight="bold">stand</tspan>'
            f'<tspan fill="{TEXT}">?</tspan>'
        )
    return msg


def render_table(s):
    W, H = 700, 292
    st = s["stats"]
    hide_hole = s["phase"] == "player"
    px, panel_r = 22, 212
    tx = 252
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">',
        f'<rect width="{W}" height="{H}" rx="10" fill="{BG}" stroke="{BORDER}"/>',
        f'<line x1="232" y1="16" x2="232" y2="{H - 16}" stroke="{BORDER}"/>',
        f'<text x="{px}" y="32" font-size="11" fill="{BLUE}" letter-spacing="2" '
        f'font-weight="bold">PODLE STATS</text>',
        f'<line x1="{px}" y1="42" x2="{panel_r}" y2="42" stroke="{BORDER}"/>',
    ]

    # gold balance
    out.append(pixel_coin(px + 1, 56, 16))
    bal_col = GOLD if s["balance"] >= BET else PINK
    out.append(
        f'<text x="{px + 26}" y="70" font-size="11" fill="{DIM}">Gold'
        f'<tspan x="{panel_r}" text-anchor="end" fill="{bal_col}" '
        f'font-weight="bold">{s["balance"]}</tspan></text>'
    )

    # lifetime podle win
    pnl = st["pnl"]
    pnl_col = LIME if pnl > 0 else PINK if pnl < 0 else TEXT
    pnl_str = f"+{pnl}" if pnl > 0 else str(pnl)
    out.append(
        f'<text x="{px}" y="96" font-size="10" fill="{DIM}">Total Podles win '
        f'<tspan font-size="8">(LIFETIME)</tspan>'
        f'<tspan x="{panel_r}" text-anchor="end" font-size="11" fill="{pnl_col}">{pnl_str}</tspan></text>'
    )
    out.append(
        f'<text x="{px}" y="120" font-size="11" fill="{DIM}">Games'
        f'<tspan x="{panel_r}" text-anchor="end" fill="{BRIGHT}">{st["games"]}</tspan></text>'
    )

    # last 10
    out.append(
        f'<text x="{px}" y="148" font-size="11" fill="{DIM}">Last 10 Rounds '
        f'<tspan font-size="8">(GLOBALLY)</tspan></text>'
    )
    for i in range(10):
        cx = px + 8 + i * 19
        if i < len(st["last"]):
            r = st["last"][i]
            col = LIME if r == "W" else PINK if r == "L" else AMBER
            out.append(f'<circle cx="{cx}" cy="168" r="8" fill="none" stroke="{col}" stroke-width="1.3"/>')
            out.append(
                f'<text x="{cx}" y="171" font-size="8" text-anchor="middle" fill="{col}">{r}</text>'
            )
        else:
            out.append(
                f'<circle cx="{cx}" cy="168" r="8" fill="none" stroke="{DIM}" '
                f'stroke-dasharray="2,3"/>'
            )

    # podle rules
    out.append(
        f'<text x="{px}" y="204" font-size="9" fill="{AMBER}" letter-spacing="2" '
        f'font-weight="bold">PODLE RULES</text>'
    )
    rules = [
        "Blackjack pays 3:2",
        "Podles stands on 17",
        "Quitting a hand = loss",
        f"Start {STAKE} gold · {BET}/hand",
    ]
    for i, rule in enumerate(rules):
        out.append(
            f'<text x="{px}" y="{222 + i * 15}" font-size="9" fill="{DIM}">· {rule}</text>'
        )

    # ── right column: deck + bet ──
    # bottom two cards plain, top card wears the shared card-back art
    for i in range(2):
        out.append(
            f'<rect x="{DECK_X + i * 2}" y="{DECK_Y - i * 2}" width="{CARD_W}" '
            f'height="{CARD_H}" rx="5" fill="{PANEL}" stroke="{DIM}"/>'
        )
    out.append(
        f'<g transform="translate({DECK_X + 4},{DECK_Y - 4})">{card_face(None, True)}</g>'
    )
    out.append(
        f'<text x="{DECK_X + CARD_W / 2 + 2}" y="{DECK_Y + CARD_H + 16}" font-size="9" '
        f'text-anchor="middle" fill="{DIM}" letter-spacing="2" font-weight="bold">DECK</text>'
    )
    bet_cx = DECK_X + CARD_W / 2 + 2
    out.append(pixel_coin(bet_cx - 26, DECK_Y + CARD_H + 36, 18))
    out.append(
        f'<text x="{bet_cx - 1}" y="{DECK_Y + CARD_H + 52}" font-size="11" '
        f'fill="{GOLD}" font-weight="bold">{BET}</text>'
    )
    out.append(
        f'<text x="{bet_cx + 2}" y="{DECK_Y + CARD_H + 68}" font-size="9" '
        f'text-anchor="middle" fill="{DIM}" letter-spacing="2" font-weight="bold">BET</text>'
    )

    # ── table area ──
    if s["phase"] == "idle":
        cx = (tx + DECK_X) / 2 - 10
        out.append(
            f'<text x="{cx}" y="64" font-size="17" text-anchor="middle" fill="{BRIGHT}" '
            f'letter-spacing="5" font-weight="bold"><tspan fill="{BLUE}">♠</tspan> '
            f'INFINITE BLACKJACK <tspan fill="{PINK}">♥</tspan></text>'
        )
        out.append(
            f'<text x="{cx}" y="112" font-size="14" text-anchor="middle" fill="{BRIGHT}" '
            f'letter-spacing="2">▮ NO HAND IN PLAY</text>'
        )
        out.append(
            f'<text x="{cx}" y="140" font-size="11" text-anchor="middle" fill="{TEXT}">'
            f'press <tspan fill="{AMBER}">▶ PLAY</tspan> to sit down with '
            f'<tspan fill="{GOLD}">{STAKE} gold</tspan></text>'
        )
        out.append(
            f'<text x="{cx}" y="160" font-size="10" text-anchor="middle" fill="{DIM}">'
            f'{BET} a hand · podles stands on 17</text>'
        )
    elif s["phase"] == "broke":
        cx = (tx + DECK_X) / 2 - 10
        led = s["ledger"]
        me = s["session"]
        out.append(
            f'<text x="{cx}" y="52" font-size="16" text-anchor="middle" fill="{BRIGHT}" '
            f'letter-spacing="3" font-weight="bold">'
            f'<tspan font-size="21">☠</tspan> OUT OF GOLD <tspan font-size="21">☠</tspan></text>'
        )
        out.append(
            f'<text x="{cx}" y="80" font-size="12" text-anchor="middle" fill="{BRIGHT}" '
            f'font-weight="bold">YOUR SCORE: <tspan fill="{AMBER}">PEAKED '
            f'+{me["peak"] - STAKE} Gold · {me["hands"]} Hands</tspan></text>'
        )
        lx, ex = tx + 16, tx + 104
        y = 106
        for label, col, runs in (("Best Runs:", LIME, led["best"][:3]),
                                 ("Worst Runs:", PINK, led["worst"][:3])):
            out.append(
                f'<text x="{lx}" y="{y}" font-size="10" fill="{col}" '
                f'font-weight="bold">{label}</text>'
            )
            for i, e in enumerate(runs):
                out.append(
                    f'<text x="{ex}" y="{y + i * 15}" font-size="10" fill="{col}">'
                    f'{i + 1}. +{e["peak_net"]} gold · {e["hands"]} hands · '
                    f'@{e["by"]}</text>'
                )
            y += max(len(runs), 1) * 15 + 12
        out.append(
            f'<text x="{cx}" y="{y + 4}" font-size="10" '
            f'text-anchor="middle" fill="{TEXT}">press <tspan fill="{AMBER}">▶ PLAY</tspan> '
            f'to re-buy <tspan fill="{GOLD}">{STAKE} gold</tspan></text>'
        )
    else:
        dv = hand_value(s["dealer"])
        pv = hand_value(s["player"])
        dshown = "??" if hide_hole else dv
        out.append(
            f'<text x="{tx}" y="34" font-size="11" fill="{AMBER}" letter-spacing="1" '
            f'font-weight="bold">PODLES <tspan fill="{AMBER}">[{dshown}]</tspan></text>'
        )
        for i, c in enumerate(s["dealer"]):
            out.append(
                dealt_card(tx + i * (CARD_W + 8), 42, c, 0.25 + i * 0.22,
                           hidden=hide_hole and i == 1)
            )
        out.append(
            f'<text x="{tx}" y="134" font-size="11" fill="{DIM}" letter-spacing="1" '
            f'font-weight="bold">PLAYER '
            f'<tspan fill="{BLUE}">[{pv}]</tspan></text>'
        )
        for i, c in enumerate(s["player"]):
            out.append(dealt_card(tx + i * (CARD_W + 8), 142, c, 0.14 + i * 0.22))

    # message line
    msg_col = TEXT if s["phase"] == "player" else AMBER if s["phase"] == "idle" else BRIGHT
    if s["phase"] == "broke":
        msg_col = PINK
    out.append(
        f'<text x="{tx}" y="{H - 16}" font-size="11" fill="{msg_col}">'
        f'&gt; {msg_markup(s)}<tspan fill="{BLUE}"> ▌'
        f'<animate attributeName="opacity" values="1;0;1" dur="1.2s" repeatCount="indefinite"/>'
        f'</tspan></text>'
    )
    out.append("</svg>")
    return "".join(out)


def render_button(label, sub, color, active):
    W, H = 150, 44
    if not active:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}" font-family="{MONO}">'
            f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="8" fill="{BG}" '
            f'stroke="{DIM}" stroke-dasharray="3,4" opacity="0.6"/>'
            f'<text x="{W / 2}" y="20" font-size="12" text-anchor="middle" '
            f'fill="{DIM}" letter-spacing="2">{label}</text>'
            f'<text x="{W / 2}" y="34" font-size="8" text-anchor="middle" '
            f'fill="{DIM}" letter-spacing="1">— locked —</text></svg>'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">'
        f'<rect x="1" y="1" width="{W - 2}" height="{H - 2}" rx="8" fill="{PANEL}" '
        f'stroke="{color}" stroke-width="1.5">'
        f'<animate attributeName="stroke-opacity" values="1;0.35;1" dur="1.8s" '
        f'repeatCount="indefinite"/></rect>'
        f'<text x="{W / 2}" y="20" font-size="12" text-anchor="middle" fill="{color}" '
        f'letter-spacing="2" font-weight="bold">{label}</text>'
        f'<text x="{W / 2}" y="34" font-size="8" text-anchor="middle" fill="{TEXT}" '
        f'letter-spacing="1">{sub}</text></svg>'
    )


def render_buttons(s):
    live = s["phase"] == "player"
    if live:
        play = render_button("⟳ REDEAL", f"abandons hand · -{BET} gold", AMBER, True)
    elif s["phase"] == "broke":
        play = render_button("▶ REBUY", f"fresh {STAKE} gold", AMBER, True)
    else:
        play = render_button("▶ PLAY", f"deal a hand · {BET} gold", AMBER, True)
    hit = render_button("+ HIT", "draw another card", BLUE, live)
    stand = render_button("■ STAND", "podles plays out", PINK, live)
    for name, svg in (("btn_play", play), ("btn_hit", hit), ("btn_stand", stand)):
        with open(os.path.join(ASSETS, f"{name}.svg"), "w", encoding="utf-8") as f:
            f.write(svg)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    global PLAYER
    move = sys.argv[1] if len(sys.argv) > 1 else "deal"
    if move not in ("init", "deal", "hit", "stand"):
        sys.exit(f"unknown move: {move}")
    if len(sys.argv) > 2 and sys.argv[2].strip():
        PLAYER = sys.argv[2].strip()
    s = fresh_state() if move == "init" else load()
    if move != "init":
        act(s, move)
    save(s)
    with open(os.path.join(ASSETS, "blackjack.svg"), "w", encoding="utf-8") as f:
        f.write(render_table(s))
    render_buttons(s)
    print(s["msg"])


if __name__ == "__main__":
    main()
