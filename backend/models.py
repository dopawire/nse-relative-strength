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
    l: float | None      # last traded price
    h: float | None      # % off 52-week high
    a: float | None      # ADR%


class GroupOut(BaseModel):
    id: int
    name: str
    n: int               # n_constituents
    pct: float           # group RS_STS% (0..1)
    r: list[float]       # group rs_series
    members: list[MemberOut]


class LevelResponse(BaseModel):
    key: str
    label: str
    groups: list[GroupOut]


class BreadthResponse(BaseModel):
    dates: list[str]
    osc: list[float]
    n: int
    latest: float
    span: str
