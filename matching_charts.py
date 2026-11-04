"""Seaborn recommendation charts; scores are not ownership probabilities."""
import io
import threading

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager, rc_context
from matplotlib.figure import Figure
import seaborn as sns

PARTS = {"category_score":"종류", "color_score":"색상", "keyword_score":"특징", "location_score":"위치"}
LOCK = threading.RLock()
BACKGROUND = "#17191b"
TEXT = "#ebedef"
MUTED = "#959da3"
GREEN = "#1ed760"


def score_charts(result):
    if result.empty:
        return None
    top = result.sort_values(["score", "found_at"], ascending=False).head(10).copy()
    top["label"] = [f"{i:02d}   {str(r.title)[:24]}  · #{r.id}" for i,r in enumerate(top.itertuples(),1)]
    maximum = max(1, result.attrs.get("score_max", 100))
    limits = result.attrs.get("score_limits", dict(zip(PARTS, (40,20,20,20))))
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    family = next((f for f in ("Malgun Gothic", "AppleGothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "NanumGothic") if f in fonts), "DejaVu Sans")
    def png(fig):
        stream = io.BytesIO()
        fig.savefig(stream, format="png", dpi=160, facecolor=BACKGROUND, bbox_inches="tight", pad_inches=.25)
        fig.clear()
        return stream.getvalue()
    def axis(fig):
        ax = fig.subplots()
        ax.set_facecolor(BACKGROUND)
        ax.tick_params(colors=MUTED, length=0, pad=12)
        for spine in ax.spines.values():
            spine.set_visible(False)
        return ax
    with LOCK, rc_context({"font.family":family, "axes.unicode_minus":False, "font.size":11,
                           "text.color":TEXT,"axes.labelcolor":MUTED,"text.usetex":False}):
        height = max(2.6, .58 * len(top) + 1.3)
        fig = Figure(figsize=(10.4,height), facecolor=BACKGROUND, layout="constrained")
        ax = axis(fig)
        ax.barh(range(len(top)), [maximum]*len(top), color="#292d31", height=.34, zorder=1)
        palette = {label:GREEN if i==0 else "#47956b" for i,label in enumerate(top.label)}
        sns.barplot(data=top, y="label", x="score", hue="label", palette=palette,
                    order=top.label.tolist(), dodge=False, legend=False, errorbar=None,
                    saturation=1, width=.34, ax=ax, zorder=3)
        ax.set(xlim=(0,maximum*1.19), xlabel="", ylabel="")
        ax.set_xticks([maximum*t/4 for t in range(5)])
        ax.set_xticklabels([f"{maximum*t/4:g}" for t in range(5)], fontsize=9)
        ax.tick_params(axis="y", colors=TEXT, labelsize=11)
        ax.set_title("비슷한 물건 순위", loc="left", fontsize=15, weight="bold", color=TEXT, pad=25)
        for i,score in enumerate(top.score):
            ax.text(maximum*1.04,i,f"{score:.1f}",va="center",ha="left",color=GREEN if i==0 else TEXT,weight="bold",fontsize=12)
        ax.text(1,1.035,f"최대 {maximum:g}점",transform=ax.transAxes,ha="right",fontsize=9,color=MUTED)
        total = png(fig)

        fig = Figure(figsize=(10.4,height), facecolor=BACKGROUND, layout="constrained")
        ax = axis(fig)
        matrix = top.set_index("label")[list(PARTS)].astype(float)
        annotation = matrix.copy().astype(object)
        for key in PARTS:
            limit=limits.get(key,0)
            annotation[key]=[f"{v:.1f}".removesuffix(".0")+f" / {limit}" if limit else "—" for v in matrix[key]]
            matrix[key] = matrix[key]/limit if limit else 0
        matrix.columns=[f"{name}\n최대 {limits.get(key,0)}점" if limits.get(key,0) else f"{name}\n조건 없음" for key,name in PARTS.items()]
        cmap=sns.blend_palette(["#252a2d","#28533e","#1ed760"],as_cmap=True)
        sns.heatmap(matrix, annot=annotation.to_numpy(), fmt="", cmap=cmap, vmin=0, vmax=1,
                    cbar=False, linewidths=7, linecolor=BACKGROUND, annot_kws={"fontsize":11}, ax=ax)
        for text,value in zip(ax.texts,matrix.to_numpy().flat):
            text.set_color("#092517" if value>.65 else TEXT)
            text.set_weight("bold" if value>.65 else "normal")
        ax.set(xlabel="",ylabel="")
        ax.set_title("어떤 특징이 일치했나요?",loc="left",fontsize=15,weight="bold",color=TEXT,pad=25)
        ax.xaxis.tick_top()
        ax.tick_params(axis="x",labelrotation=0,colors=MUTED,labelsize=10)
        ax.tick_params(axis="y",labelrotation=0,colors=TEXT,labelsize=11)
        breakdown=png(fig)
    return total,breakdown
