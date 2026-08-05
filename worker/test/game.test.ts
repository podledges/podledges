import { describe, expect, it } from "vitest";
import { applyMove, freshState, handValue, hydrateState } from "../src/game";

describe("shared blackjack game", () => {
  it("starts with a complete, idle state", () => {
    expect(freshState()).toEqual({
      phase: "idle",
      deck: [],
      player: [],
      dealer: [],
      msg: "table open — press play",
      balance: 200,
      session: { hands: 0, peak: 200, players: {} },
      ledger: { best: [], worst: [] },
      stats: { games: 0, pnl: 0, last: [] },
    });
  });

  it("matches blackjack ace scoring", () => {
    expect(handValue(["A♠", "K♥"])).toBe(21);
    expect(handValue(["A♠", "A♥", "9♦"])).toBe(21);
    expect(handValue(["A♠", "A♥", "9♦", "K♣"])).toBe(21);
  });

  it("attributes a settled hand to the request's player", () => {
    const state = hydrateState({
      ...freshState(),
      phase: "player",
      deck: ["2♠"],
      player: ["2♣", "3♦"],
      dealer: ["10♠", "6♣"],
    });
    applyMove(state, "stand", "alice");
    expect(state.session.players).toEqual({ alice: 1 });
    expect(state.stats.last).toEqual(["L"]);
  });

  it("walks a completed session and starts a fresh run from walked", () => {
    const state = hydrateState({
      ...freshState(),
      phase: "done",
      balance: 300,
      session: { hands: 1, peak: 300, players: { alice: 1 } },
    });
    applyMove(state, "walk", "bob");
    expect(state.phase).toBe("walked");
    expect(state.ledger.best[0].by).toBe("alice");
    applyMove(state, "deal", "bob");
    expect(state.phase).toBe("player");
    expect(state.balance).toBe(200);
    expect(state.session).toEqual({ hands: 0, peak: 200, players: {} });
  });
});

