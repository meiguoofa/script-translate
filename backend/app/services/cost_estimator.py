def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_cost_rmb(total_tokens: int) -> float:
    return round(total_tokens * 0.00002, 4)
