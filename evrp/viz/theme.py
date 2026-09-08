"""One place for the plot palette, so every figure in the project matches."""

BACKGROUND = "#14161A"
PANEL = "#1C1F24"
GRID = "#2E333A"
TEXT = "#F2F4F7"
MUTED = "#9AA4B2"

DEPOT = "#FF6B5A"
CUSTOMER = "#4C9AFF"
STATION = "#3ED598"
WARNING = "#FFB020"
DANGER = "#FF4D4F"

ROUTE_COLORS = [
    "#4C9AFF", "#3ED598", "#FFB020", "#B57BFF", "#FF6B9D",
    "#5AD1E6", "#FF8F5A", "#9BE564", "#F26D6D", "#7FA0FF",
    "#C9A227", "#59C3C3", "#E36BAE", "#7DCE82", "#D18CFF",
]


def route_color(i: int) -> str:
    return ROUTE_COLORS[i % len(ROUTE_COLORS)]


def style_axes(ax, title: str = "", xlabel: str = "", ylabel: str = "") -> None:
    fig = ax.get_figure()
    fig.patch.set_facecolor(BACKGROUND)
    ax.set_facecolor(PANEL)
    if title:
        ax.set_title(title, color=TEXT, fontsize=14, fontweight="bold", pad=12)
    if xlabel:
        ax.set_xlabel(xlabel, color=MUTED, fontsize=11)
    if ylabel:
        ax.set_ylabel(ylabel, color=MUTED, fontsize=11)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(color=GRID, linestyle="--", linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID)


def style_legend(ax, **kwargs):
    legend = ax.legend(facecolor=PANEL, edgecolor=GRID, framealpha=0.95, **kwargs)
    for text in legend.get_texts():
        text.set_color(TEXT)
    return legend
