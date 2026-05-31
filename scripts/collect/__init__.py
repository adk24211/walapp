from .domestic_news import collect as collect_domestic
from .world_news import collect as collect_world
from .curious import collect as collect_curious
from .gov_policy import collect as collect_policy

__all__ = ["collect_domestic", "collect_world", "collect_curious", "collect_policy"]
