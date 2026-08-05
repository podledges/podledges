export const BET = 100;
export const STAKE = 200;

export const SUITS = ["♠", "♥", "♦", "♣"] as const;
export const RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"] as const;

export type Phase = "idle" | "player" | "done" | "broke" | "walked";
export type Move = "deal" | "hit" | "stand" | "walk";
export type Result = "W" | "L" | "P";

export interface LedgerEntry {
  hands: number;
  peak_net: number;
  final: number;
  by: string;
}

export interface GameState {
  phase: Phase;
  deck: string[];
  player: string[];
  dealer: string[];
  msg: string;
  balance: number;
  session: {
    hands: number;
    peak: number;
    players: Record<string, number>;
  };
  ledger: {
    best: LedgerEntry[];
    worst: LedgerEntry[];
  };
  stats: {
    games: number;
    pnl: number;
    last: Result[];
  };
}

const PHASES: readonly Phase[] = ["idle", "player", "done", "broke", "walked"];
const MOVES: readonly Move[] = ["deal", "hit", "stand", "walk"];
const CARD_RE = /^(?:A|[2-9]|10|J|Q|K)[♠♥♦♣]$/u;

export function isMove(value: unknown): value is Move {
  return typeof value === "string" && MOVES.includes(value as Move);
}

/** Names are displayed in the public ledger, so reject control characters and bound their size. */
export function normalizeName(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const name = value.trim();
  if (!name || Array.from(name).length > 20 || /[\u0000-\u001f\u007f]/u.test(name)) return null;
  return name;
}

export function freshState(): GameState {
  return {
    phase: "idle",
    deck: [],
    player: [],
    dealer: [],
    msg: "table open — press play",
    balance: STAKE,
    session: { hands: 0, peak: STAKE, players: {} },
    ledger: { best: [], worst: [] },
    stats: { games: 0, pnl: 0, last: [] },
  };
}

function finiteInteger(value: unknown, fallback: number, minimum = Number.MIN_SAFE_INTEGER): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum ? value : fallback;
}

function cards(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((card): card is string => typeof card === "string" && CARD_RE.test(card)) : [];
}

function ledgerEntries(value: unknown): LedgerEntry[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((entry): entry is Record<string, unknown> => !!entry && typeof entry === "object" && !Array.isArray(entry))
    .map((entry) => ({
      hands: finiteInteger(entry.hands, 0, 0),
      peak_net: finiteInteger(entry.peak_net, 0),
      final: finiteInteger(entry.final, 0),
      by: normalizeName(entry.by) ?? "anon",
    }))
    .slice(0, 3);
}

/** Normalize old/corrupt rows while retaining the public state shape. */
export function hydrateState(raw: unknown): GameState {
  const base = freshState();
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return base;
  const source = raw as Record<string, unknown>;
  const rawSession = source.session && typeof source.session === "object" && !Array.isArray(source.session)
    ? source.session as Record<string, unknown>
    : {};
  const rawLedger = source.ledger && typeof source.ledger === "object" && !Array.isArray(source.ledger)
    ? source.ledger as Record<string, unknown>
    : {};
  const rawStats = source.stats && typeof source.stats === "object" && !Array.isArray(source.stats)
    ? source.stats as Record<string, unknown>
    : {};
  const players: Record<string, number> = {};
  if (rawSession.players && typeof rawSession.players === "object" && !Array.isArray(rawSession.players)) {
    for (const [name, count] of Object.entries(rawSession.players)) {
      const normalized = normalizeName(name);
      if (normalized) players[normalized] = finiteInteger(count, 0, 0);
    }
  }
  const phase = PHASES.includes(source.phase as Phase) ? source.phase as Phase : base.phase;
  const state: GameState = {
    phase,
    deck: cards(source.deck),
    player: cards(source.player),
    dealer: cards(source.dealer),
    msg: typeof source.msg === "string" ? source.msg.slice(0, 500) : base.msg,
    balance: finiteInteger(source.balance, base.balance, 0),
    session: {
      hands: finiteInteger(rawSession.hands, base.session.hands, 0),
      peak: finiteInteger(rawSession.peak, base.session.peak, 0),
      players,
    },
    ledger: {
      best: ledgerEntries(rawLedger.best),
      worst: ledgerEntries(rawLedger.worst),
    },
    stats: {
      games: finiteInteger(rawStats.games, base.stats.games, 0),
      pnl: finiteInteger(rawStats.pnl, base.stats.pnl),
      last: Array.isArray(rawStats.last)
        ? rawStats.last.filter((result): result is Result => result === "W" || result === "L" || result === "P").slice(-10)
        : [],
    },
  };

  // A player-phase row must have enough cards to be actionable. Resetting an incomplete
  // row avoids a malformed SQLite value turning a valid /move into a runtime exception.
  if (state.phase === "player" && (state.player.length < 2 || state.dealer.length < 2 || state.deck.length === 0)) {
    return freshState();
  }
  return state;
}

export function newDeck(): string[] {
  const deck: string[] = [];
  for (const suit of SUITS) for (const rank of RANKS) deck.push(rank + suit);
  const random = new Uint32Array(deck.length);
  crypto.getRandomValues(random);
  for (let i = deck.length - 1; i > 0; i -= 1) {
    const j = random[i] % (i + 1);
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return deck;
}

export function handValue(hand: string[]): number {
  let total = 0;
  let aces = 0;
  for (const card of hand) {
    const rank = card.slice(0, -1);
    if (rank === "A") {
      total += 11;
      aces += 1;
    } else if ("JQK".includes(rank)) {
      total += 10;
    } else {
      total += Number(rank);
    }
  }
  while (total > 21 && aces > 0) {
    total -= 10;
    aces -= 1;
  }
  return total;
}

function endSession(state: GameState, fallbackBy: string): void {
  const players = state.session.players;
  const by = Object.entries(players).reduce(
    (best, current) => current[1] > best[1] ? current : best,
    [fallbackBy, 0] as [string, number],
  )[0];
  const entry: LedgerEntry = {
    hands: state.session.hands,
    peak_net: state.session.peak - STAKE,
    final: state.balance - STAKE,
    by,
  };
  state.ledger.best = [...state.ledger.best, entry]
    .sort((left, right) => right.peak_net - left.peak_net || left.hands - right.hands)
    .slice(0, 3);
  state.ledger.worst = [...state.ledger.worst, entry]
    .sort((left, right) => left.hands - right.hands || left.peak_net - right.peak_net)
    .slice(0, 3);
}

function settle(state: GameState, result: Result, delta: number, message: string, by: string): void {
  state.balance += delta;
  state.stats.games += 1;
  state.stats.pnl += delta;
  state.stats.last = [...state.stats.last, result].slice(-10);
  state.session.hands += 1;
  state.session.players[by] = (state.session.players[by] ?? 0) + 1;
  state.session.peak = Math.max(state.session.peak, state.balance);
  const tail = delta ? ` (${delta > 0 ? "+" : ""}${delta} gold)` : " (push)";
  if (state.balance < BET) {
    state.phase = "broke";
    endSession(state, by);
    state.msg = `${message}${tail} — out of gold.`;
  } else {
    state.phase = "done";
    state.msg = `${message}${tail}`;
  }
}

function draw(state: GameState): string | null {
  return state.deck.pop() ?? null;
}

/** Apply one validated move to the in-memory state. The Durable Object persists the result atomically. */
export function applyMove(state: GameState, move: Move, by: string): GameState {
  if (move === "walk") {
    if (state.phase !== "done") return state;
    endSession(state, by);
    const net = state.balance - STAKE;
    state.phase = "walked";
    state.msg = `you walk away with ${state.balance} gold (${net >= 0 ? "+" : ""}${net} gold).`;
    return state;
  }

  if (move === "deal") {
    if (state.phase === "player") {
      settle(state, "L", -BET, "hand abandoned", by);
      // settle() may have mutated phase to "broke"; cast defeats stale narrowing from the guard above
      if ((state.phase as Phase) === "broke") return state;
    }
    if (state.phase === "broke" || state.phase === "walked") {
      state.balance = STAKE;
      state.session = { hands: 0, peak: STAKE, players: {} };
    }
    state.deck = newDeck();
    state.player = [draw(state)!, draw(state)!];
    state.dealer = [draw(state)!, draw(state)!];
    state.phase = "player";
    const playerValue = handValue(state.player);
    const dealerValue = handValue(state.dealer);
    if (playerValue === 21 && dealerValue === 21) settle(state, "P", 0, "double blackjack — push", by);
    else if (playerValue === 21) settle(state, "W", Math.floor(BET * 1.5), "blackjack!", by);
    else if (dealerValue === 21) settle(state, "L", -BET, "podles has blackjack", by);
    else state.msg = `you show ${playerValue}. hit or stand?`;
    return state;
  }

  if (state.phase !== "player") {
    state.msg = "no live hand — press play.";
    return state;
  }

  if (move === "hit") {
    const card = draw(state);
    if (!card) {
      state.phase = "idle";
      state.player = [];
      state.dealer = [];
      state.msg = "table reset — press play.";
      return state;
    }
    state.player.push(card);
    const playerValue = handValue(state.player);
    if (playerValue > 21) settle(state, "L", -BET, `bust at ${playerValue}`, by);
    else if (playerValue === 21) applyMove(state, "stand", by);
    else state.msg = `drew ${card} — ${playerValue}. hit or stand?`;
  } else if (move === "stand") {
    while (handValue(state.dealer) < 17) {
      const card = draw(state);
      if (!card) break;
      state.dealer.push(card);
    }
    const playerValue = handValue(state.player);
    const dealerValue = handValue(state.dealer);
    if (dealerValue > 21) settle(state, "W", BET, `podles busts at ${dealerValue}`, by);
    else if (playerValue > dealerValue) settle(state, "W", BET, `${playerValue} beats ${dealerValue}`, by);
    else if (playerValue < dealerValue) settle(state, "L", -BET, `${dealerValue} beats ${playerValue}`, by);
    else settle(state, "P", 0, `push at ${playerValue}`, by);
  }
  return state;
}

