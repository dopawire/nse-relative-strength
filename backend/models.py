from pydantic import BaseModel


class MetaResponse(BaseModel):
    benchmark: str
    window: int
    drange: str
    generated: str
    n_stocks: int
    n_groups_per_level: list[int]
    n_window: int = 0          # stocks with full window data (in the levels)
    excluded: list[str] = []   # stocks with price data but no window coverage
    src: dict[str, str] = {}   # {date: source} for non-Yahoo benchmark bars
    ipo: list[dict] = []       # new listings awaiting their first ranking


class LevelSummary(BaseModel):
    key: str
    label: str
    n_groups: int


class MemberOut(BaseModel):
    n: str               # name
    s: str               # symbol
    r: list[float]       # rs_series (26 values for sparkline)
    p: float             # RS_STS% (0..1)
    e: list[int]         # EMA flags [-1,0,1] × 5
    b: int               # RS line vs its EMA21: 1=above, 0=below, -1=n/a
    d: float | None = None   # RS_STS% change vs previous snapshot (pp)
    l: float | None = None  # noqa: E741 — last traded price (data key 'l')
    h: float | None      # % off 52-week high
    a: float | None      # ADR%


class GroupOut(BaseModel):
    id: int
    name: str
    n: int               # n_constituents
    pct: float           # group RS_STS% (0..1)
    dp: float | None = None  # RS_STS% change vs previous snapshot (pp)
    r: list[float]       # group rs_series
    members: list[MemberOut]


class LevelResponse(BaseModel):
    key: str
    label: str
    groups: list[GroupOut]


class MacroBreadth(BaseModel):
    name: str
    dates: list[str]
    osc: list[float]
    latest: float


class BreadthResponse(BaseModel):
    dates: list[str]
    osc: list[float]
    n: int
    latest: float
    span: str
    macros: list[MacroBreadth] = []
    divergence: dict = {}


class RotationGroup(BaseModel):
    name: str
    rs: list[float]


class RotationResponse(BaseModel):
    dates: list[str]
    groups: list[RotationGroup] = []


class StockDetail(BaseModel):
    sym: str
    name: str = ""
    dates: list[str]       # ~125 recent trading days
    rs: list[float]        # RS line = stock / NIFTY 500 (TradingView style)
    ema21: list[float]     # 21-day EMA of the RS line
    ltp: float
    rse: int               # 1 = above EMA21, 0 = below
