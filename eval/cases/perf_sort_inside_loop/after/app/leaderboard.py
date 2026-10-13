"""Leaderboard helpers."""


def positions(results: list[tuple[str, int]]) -> dict[str, int]:
    scores: list[int] = []
    positions: dict[str, int] = {}
    for player, score in results:
        scores.append(score)
        ranking = sorted(scores, reverse=True)
        positions[player] = ranking.index(score) + 1
    return positions
