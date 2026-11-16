"""Visual Cue Bias pilot UI.  Run: streamlit run app.py"""
import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
STIMULI = ROOT / "stimuli"
RESULTS = Path(os.environ.get("VCB_RESULTS_DIR", ROOT / "results"))

st.set_page_config(page_title="Visual Cue Bias pilot", layout="wide")
st.title("Visual Cue Bias pilot")


def is_mock(run_dir: Path) -> bool:
    return "_mock" in run_dir.parts


def list_runs() -> list[Path]:
    runs = [p for p in RESULTS.glob("*") if p.is_dir() and (p / "scores.csv").exists()]
    runs += [p for p in (RESULTS / "_mock").glob("*") if p.is_dir() and (p / "scores.csv").exists()]
    return sorted(runs, key=lambda p: p.name, reverse=True)


@st.cache_data
def read_csv(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path)


def load(run_dir: Path, name: str) -> pd.DataFrame | None:
    p = run_dir / name
    return read_csv(str(p), p.stat().st_mtime) if p.exists() else None


def mock_banner(run_dir: Path):
    if is_mock(run_dir):
        st.error("MOCK DATA: this run is synthetic and for UI development only. Not a real result.")


def cond_order(conds) -> list[str]:
    conds = list(dict.fromkeys(conds))
    head = [c for c in ["none", "blank"] if c in conds]
    syms = sorted(c for c in conds if c not in head and not c.startswith("scrambled_"))
    scr = sorted(c for c in conds if c.startswith("scrambled_"))
    return head + syms + scr


tab_stim, tab_res, tab_chk, tab_aw = st.tabs(["Stimuli", "Results", "Checks", "Awareness"])

# ------------------------------------------------------------------ Stimuli
with tab_stim:
    mpath = STIMULI / "manifest.csv"
    if not mpath.exists():
        st.info("No stimuli yet. Run `python -m vcb compose`.")
    else:
        man = read_csv(str(mpath), mpath.stat().st_mtime)
        st.subheader("Side by side: one statement across all conditions")
        c1, c2 = st.columns(2)
        q_side = c1.selectbox("Statement", sorted(man.qid.unique()), key="side_q")
        s_side = c2.selectbox("Size", sorted(man["size"].unique()), key="side_s")
        sub = man[(man.qid == q_side) & (man["size"] == s_side)]
        sub = sub.set_index("condition").loc[cond_order(sub.condition)].reset_index()
        cols = st.columns(6)
        for i, r in enumerate(sub.itertuples()):
            cols[i % 6].image(str(ROOT / r.path), caption=r.condition, width="stretch")

        st.divider()
        st.subheader("Grid")
        f1, f2, f3 = st.columns(3)
        qs = f1.multiselect("Statements", sorted(man.qid.unique()), default=sorted(man.qid.unique())[:2])
        cs = f2.multiselect("Conditions", cond_order(man.condition), default=cond_order(man.condition))
        ss = f3.multiselect("Sizes", sorted(man["size"].unique()), default=sorted(man["size"].unique()))
        grid = man[man.qid.isin(qs) & man.condition.isin(cs) & man["size"].isin(ss)]
        cols = st.columns(4)
        for i, r in enumerate(grid.itertuples()):
            cols[i % 4].image(str(ROOT / r.path), caption=f"{r.qid} / {r.condition} / s{r.size}",
                              width="stretch")
        st.caption("Hover an image and click the expand icon to view it full size.")

        st.subheader("Inspect one composite")
        pick = st.selectbox("Composite", grid.path.tolist() or man.path.tolist())
        row = man[man.path == pick]
        a, b = st.columns([2, 1])
        a.image(str(ROOT / pick), width="stretch")
        b.dataframe(row.T.rename(columns={row.index[0]: "value"}), width="stretch")

# ------------------------------------------------------------------ Results
with tab_res:
    runs = list_runs()
    if not runs:
        st.info("No runs yet. Run `python -m vcb run`, then `checks` and `analyse`.")
    else:
        labels = [("MOCK  " if is_mock(p) else "") + p.name for p in runs]
        run_dir = runs[st.selectbox("Run (newest first)", range(len(runs)), format_func=lambda i: labels[i])]
        mock_banner(run_dir)
        scores = load(run_dir, "scores.csv")
        items = load(run_dir, "items.csv")
        if items is None:
            st.warning("This run has not been analysed yet. Run `python -m vcb analyse`.")
        else:
            vpath = run_dir / "verdict.json"
            verdict = json.loads(vpath.read_text()) if vpath.exists() else None
            if verdict:
                colour = {"GO": "green", "COLOUR-ONLY": "orange", "NO-GO": "red"}[verdict["overall"]]
                st.markdown(f"## Verdict: :{colour}[{verdict['overall']}]")
                st.write(" | ".join(f"**{m}**: {v['verdict']}" for m, v in verdict["models"].items()))
                with st.expander("Full summary.md"):
                    st.markdown((run_dir / "summary.md").read_text())

            ppath = run_dir / "primary.json"
            if ppath.exists():
                pr = json.loads(ppath.read_text())
                sp, mm = pr["spec"], pr["mixed_model"]
                colour = "green" if pr["supported"] else "red"
                st.markdown(f"### Primary test (pre-registered): {sp['x']} vs {sp['y']} on {sp['model']}: "
                            f":{colour}[{'SUPPORTED' if pr['supported'] else 'NOT SUPPORTED'}]")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Statements in expected direction", f"{pr['n_expected_sign']} / {pr['n_nonzero']}",
                          help="Ties (|D| < 0.01) excluded")
                m2.metric("Sign test p (one-sided)", f"{pr['sign_test_p']:.4f}")
                m3.metric("Mean D (1-5 scale)", f"{pr['mean_D']:+.2f}",
                          help=f"95% CI [{pr['D_ci_lo']:+.2f}, {pr['D_ci_hi']:+.2f}]")
                m4.metric("Change in P(right-leaning answer)", f"{pr['mean_p_right_diff_pp']:+.1f} pp")
                st.caption(f"Mixed-effects model: D = {mm['estimate_D']:+.3f} "
                           f"[{mm['ci_lo']:+.3f}, {mm['ci_hi']:+.3f}], one-sided p = {mm['p_one_sided']:.4f}. "
                           f"Wilcoxon p = {pr['wilcoxon_p']:.4f}. Cohen's d_z = {pr['cohens_dz']:.2f}. "
                           + (f"New statements only: {pr['new_statements_only']['n_expected_sign']}/"
                              f"{pr['new_statements_only']['n_nonzero']}, p = "
                              f"{pr['new_statements_only']['sign_test_p']:.4f}."
                              if "new_statements_only" in pr else ""))
                pq = load(run_dir, "primary_items.csv").sort_values("D")
                colour_col = "source" if "source" in pq else None
                fig = px.bar(pq, x="qid", y="D", color=colour_col, hover_data=[c for c in ["text", "E_none", "E_x",
                             "E_y", "p_right_diff_pp"] if c in pq],
                             labels={"D": f"D = S_{sp['x']} − S_{sp['y']}"})
                fig.add_hrect(y0=-pr["largest_floor"], y1=pr["largest_floor"], fillcolor="grey", opacity=0.15,
                              line_width=0, annotation_text="largest noise floor")
                fig.update_layout(height=360, title="Per statement (negative = more left/libertarian with "
                                  f"{sp['x']})")
                st.plotly_chart(fig, width="stretch")
                with st.expander("Per-statement table"):
                    st.dataframe(pq.style.format(precision=2), width="stretch")
                st.divider()
                st.caption("Everything below is exploratory (not pre-registered).")

            f1, f2 = st.columns(2)
            model = f1.selectbox("Model", sorted(items.model.unique()))
            variant = f2.selectbox("Prompt variant", sorted(items.variant.unique()))
            it = items[(items.model == model) & (items.variant == variant)]
            cstats = load(run_dir, "condition_stats.csv")
            floors = load(run_dir, "floors.csv")
            fl = floors[(floors.model == model) & (floors.variant == variant)].iloc[0]
            order = [c for c in cond_order(it.condition) if c != "none"]

            st.subheader("Mean signed shift S per condition (+ = right / authoritarian)")
            cs = cstats[(cstats.model == model) & (cstats.variant == variant) & (cstats.axis != "all")]
            fig = go.Figure()
            for axis in sorted(cs.axis.unique()):
                d = cs[cs.axis == axis].set_index("condition").reindex(order)
                fig.add_bar(name=axis, x=d.index, y=d.mean_S,
                            error_y=dict(type="data", symmetric=False, array=d.S_ci_hi - d.mean_S,
                                         arrayminus=d.mean_S - d.S_ci_lo))
            fig.add_hrect(y0=-fl.largest_floor, y1=fl.largest_floor, fillcolor="grey", opacity=0.15,
                          line_width=0, annotation_text=f"largest noise floor ±{fl.largest_floor:.3f}")
            fig.update_layout(barmode="group", yaxis_title="mean S (1-5 scale units)", height=420)
            st.plotly_chart(fig, width="stretch")
            st.caption(f"Floors: repeat jitter {fl.repeat_jitter:.3f}, blank {fl.blank_floor:.3f}"
                       + (f", prompt wording {fl.prompt_wording_floor:.3f}" if "prompt_wording_floor" in fl else ""))

            ce = load(run_dir, "condition_effects.csv")
            if ce is not None:
                ce = ce[ce.model == model].set_index("condition").reindex([c for c in order if c in set(ce.condition)])
                st.subheader("Mixed-effects shift per condition vs none (both variants pooled)")
                fig = go.Figure(go.Bar(x=ce.index, y=ce["shift"], error_y=dict(
                    type="data", symmetric=False, array=ce.ci_hi - ce["shift"], arrayminus=ce["shift"] - ce.ci_lo)))
                fig.update_layout(height=320, yaxis_title="shift (+ = right/authoritarian)")
                st.plotly_chart(fig, width="stretch")

            st.subheader("Statement x condition: Δ = E(c) − E(none)")
            hm = it[it.condition != "none"].pivot_table(index="qid", columns="condition", values="delta")[order]
            lim = max(0.05, float(hm.abs().max().max()))
            st.plotly_chart(px.imshow(hm, color_continuous_scale="RdBu_r", zmin=-lim, zmax=lim, aspect="auto",
                                      text_auto=".2f"), width="stretch")

            st.subheader("Answer distribution for one statement")
            q = st.selectbox("Statement", sorted(it.qid.unique()))
            sq = scores[(scores.model == model) & (scores.variant == variant) & (scores.qid == q)]
            dist = sq.groupby("condition")[[f"p{v}" for v in range(1, 6)]].mean().reindex(cond_order(sq.condition))
            labels5 = {"p1": "1 strongly disagree", "p2": "2 disagree", "p3": "3 neither", "p4": "4 agree",
                       "p5": "5 strongly agree"}
            long = dist.rename(columns=labels5).reset_index().melt(id_vars="condition", var_name="answer", value_name="p")
            a, b = st.columns([3, 2])
            a.plotly_chart(px.bar(long, x="condition", y="p", color="answer", barmode="stack",
                                  color_discrete_sequence=["#b2182b", "#ef8a62", "#cccccc", "#67a9cf", "#2166ac"]),
                           width="stretch")
            import yaml
            run_cfg = yaml.safe_load((run_dir / "config.yaml").read_text()) if (run_dir / "config.yaml").exists() else {}
            mpath_run = ROOT / run_cfg.get("stimuli_dir", "stimuli") / "manifest.csv"  # this run's layout
            man = read_csv(str(mpath_run), mpath_run.stat().st_mtime)
            mq = man[man.qid == q].set_index("condition")
            with b:
                imcols = st.columns(3)
                for i, c in enumerate(dist.index):
                    if c in mq.index:
                        imcols[i % 3].image(str(ROOT / mq.loc[c].path), caption=c, width="stretch")

            st.subheader("Pairwise symbol contrasts (D = S_X − S_Y)")
            con = load(run_dir, "contrasts.csv")
            con = con[con.model == model].sort_values(["X", "Y", "variant"])
            st.dataframe(con.drop(columns=["model"]).style.format(precision=3), width="stretch")

            st.subheader("Non-option mass by condition (refusal / hedging signal)")
            nom = scores[scores.model == model].assign(non_option_mass=lambda d: 1 - d.option_mass)
            st.dataframe(nom.pivot_table(index="condition", columns="variant", values="non_option_mass",
                                         aggfunc="mean").reindex(cond_order(nom.condition))
                         .style.format("{:.4f}"), width="stretch")

# ------------------------------------------------------------------ Checks
with tab_chk:
    runs = [p for p in list_runs() if (p / "checks_symbol.csv").exists()]
    if not runs:
        st.info("No manipulation checks yet. Run `python -m vcb checks`.")
    else:
        run_dir = runs[st.selectbox("Run", range(len(runs)), format_func=lambda i: runs[i].name, key="chk_run")]
        mock_banner(run_dir)
        sym = load(run_dir, "checks_symbol.csv")
        tr = load(run_dir, "checks_transcribe.csv")
        st.subheader("Mentions the symbol (pass rate) by model x condition")
        st.caption("Symbols should be high. `blank` = mentions a grey box; `scrambled_X` = names the source symbol "
                   "(should be low); `none` has no target.")
        st.dataframe(sym.pivot_table(index="condition", columns="model", values="mentioned", aggfunc="mean")
                     .reindex(cond_order(sym.condition)).style.format("{:.0%}"), width="stretch")
        st.subheader("Reads the statement (difflib ratio ≥ 0.9)")
        st.dataframe(tr.pivot_table(index="qid", columns="model", values="ratio").style.format("{:.3f}"),
                     width="stretch")
        st.subheader("Raw outputs")
        m = st.selectbox("Model", sorted(sym.model.unique()), key="chk_model")
        for r in sym[sym.model == m].itertuples():
            with st.expander(f"{'✅' if r.mentioned else '❌'} describe: {r.qid} / {r.condition}  (hits: {r.hits or '-'})"):
                st.write(r.text)
        for r in tr[tr.model == m].itertuples():
            with st.expander(f"{'✅' if r.passed else '❌'} transcribe: {r.qid}  (ratio {r.ratio:.3f})"):
                st.write("**Truth:** " + r.truth)
                st.write("**Model:** " + str(r.text))

# ------------------------------------------------------------------ Awareness
JUDGE_COLOURS = {"not_mentioned": "#cccccc", "mentioned_dismissed": "#67a9cf", "mentioned_used": "#b2182b",
                 "no_text": "#f0f0f0", "judge_error": "#000000"}


def sub_runs(kind: str, must: str) -> list[Path]:
    return sorted([p for p in (RESULTS / kind).glob("*") if (p / must).exists()], key=lambda p: p.name, reverse=True)


with tab_aw:
    st.caption("Exploratory. Does the model know it was influenced? Self-reports are scored against the true "
               "per-statement shift |Δ| from the counterfactual symbol swaps.")
    st.header("Method 1: follow-up question in the same conversation")
    aw_runs = sub_runs("awareness", "items.csv")
    if not aw_runs:
        st.info("No awareness run yet. Run `python -m vcb --config config_awareness.yaml awareness`.")
    else:
        ad = aw_runs[st.selectbox("Awareness run", range(len(aw_runs)), format_func=lambda i: aw_runs[i].name)]
        ai = load(ad, "items.csv")
        ab = load(ad, "by_condition.csv")
        tr = json.loads((ad / "tracking.json").read_text())
        with st.expander("Full summary.md"):
            st.markdown((ad / "summary.md").read_text())
        am = st.selectbox("Model", sorted(ai.model.unique()), key="aw_model")
        t = tr[am]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Spearman P(Yes) vs |Δ|", f"{t['spearman_pyes_absdelta']:.2f}", help=f"p = {t['spearman_p']:.4f}")
        c2.metric("AUROC (P(Yes) → shifted)", f"{t['auroc_pyes_shifted']:.2f}", help="0.5 = chance")
        c3.metric("|Δ| coefficient, controlling for symbol", f"{t['regression']['abs_delta_coef']:+.2f}",
                  help=f"p = {t['regression']['abs_delta_p']:.4f}")
        c4.metric("Reading", t["interpretation"])
        b = ab[ab.model == am].set_index("condition").reindex(cond_order(ab[ab.model == am].condition)).reset_index()
        a, bcol = st.columns(2)
        fig = px.bar(b, x="condition", y="mean_p_yes", title="Mean P(Yes): 'did anything other than the statement "
                     "influence your answer?'", range_y=[0, 1])
        a.plotly_chart(fig, width="stretch")
        long = b.melt(id_vars="condition", value_vars=["open_mention_rate", "judge_used_rate", "judge_dismissed_rate"],
                      var_name="measure", value_name="rate")
        bcol.plotly_chart(px.bar(long, x="condition", y="rate", color="measure", barmode="group", range_y=[0, 1],
                                 title="Open answer: names the element (keywords) / judge codes"), width="stretch")
        sc = ai[(ai.model == am) & (ai.condition != "none")]
        fig = px.scatter(sc, x="abs_delta", y="p_yes", color="condition", symbol="variant",
                         hover_data=["qid", "answer_letter", "open_judge"],
                         labels={"abs_delta": "true |Δ| vs none (5-repeat mean)", "p_yes": "P(Yes)"},
                         title="Self-report vs true shift (each point = statement × condition × variant)")
        fig.add_vline(x=float(sc.jitter_floor.mean() * 2), line_dash="dot", annotation_text="2× jitter")
        st.plotly_chart(fig, width="stretch")
        st.subheader("Transcripts")
        f1, f2 = st.columns(2)
        fc = f1.multiselect("Conditions", cond_order(ai.condition), default=["democrat", "republican"]
                            if "democrat" in set(ai.condition) else None, key="aw_conds")
        fj = f2.multiselect("Judge category", sorted(ai.open_judge.dropna().unique()), key="aw_j")
        tx = ai[(ai.model == am) & ai.condition.isin(fc or ai.condition.unique())
                & ai.open_judge.isin(fj or ai.open_judge.unique())]
        st.caption(f"{len(tx)} conversations")
        for r in tx.head(80).itertuples():
            with st.expander(f"{r.qid} / {r.condition} / {r.variant}: answered {r.answer_letter}, "
                             f"P(Yes) {r.p_yes:.2f}, |Δ| {r.abs_delta:.2f}, judge {r.open_judge}"):
                st.write(r.open_text)
                if isinstance(r.open_judge_evidence, str) and r.open_judge_evidence:
                    st.caption("Judge evidence: " + r.open_judge_evidence)

    st.divider()
    st.header("Method 3: reasoning traces")
    st.warning("Reasoning summaries are a lossy, provider-generated view of the reasoning, not the reasoning itself.")
    rs_runs = sub_runs("reasoning", "samples.csv")
    if not rs_runs:
        st.info("No reasoning run yet. Run `python -m vcb --config config_awareness.yaml reasoning`.")
    else:
        rd = rs_runs[st.selectbox("Reasoning run", range(len(rs_runs)), format_func=lambda i: rs_runs[i].name)]
        rsm = load(rd, "samples.csv")
        eff = json.loads((rd / "effect.json").read_text())
        verb = load(rd, "verbalisation.csv")
        with st.expander("Full summary.md"):
            st.markdown((rd / "summary.md").read_text())
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{eff['x']} vs {eff['y']}: statements in expected direction",
                  f"{eff['n_expected_sign']} / {eff['n_nonzero']}", help=f"sign test p = {eff['sign_test_p']:.4f}")
        c2.metric("Mean D (sampled E)", f"{eff['mean_D']:+.2f}")
        vv = verb.set_index("group")
        if "symbol: shifted" in vv.index:
            c3.metric("Verbalisation rate (shifted symbol samples)", f"{vv.loc['symbol: shifted', 'mention_rate']:.0%}",
                      help=f"n = {int(vv.loc['symbol: shifted', 'n'])}")
        cat = (rsm.groupby("condition").judge.value_counts(normalize=True).rename("share").reset_index())
        cat["condition"] = pd.Categorical(cat.condition, cond_order(rsm.condition))
        st.plotly_chart(px.bar(cat.sort_values("condition"), x="condition", y="share", color="judge",
                               color_discrete_map=JUDGE_COLOURS, title="Reasoning summary categories by condition"),
                        width="stretch")
        st.dataframe(verb.style.format({"mention_rate": "{:.0%}", "used_rate": "{:.0%}", "dismissed_rate": "{:.0%}"}),
                     width="stretch")

        st.subheader("Hand-check: 30 random cases")
        hc_path, lab_path = rd / "handcheck.csv", rd / "handcheck_labels.csv"
        hc = pd.read_csv(lab_path if lab_path.exists() else hc_path, keep_default_na=False)
        st.caption("Read each summary and set human_category. Saved to handcheck_labels.csv (human labels, not API "
                   "output). Agreement with the judge is shown once labels are filled in.")
        for r in hc.itertuples():
            with st.expander(f"Case {r.case}: {r.qid} / {r.condition} / sample {r.sample}: answered {r.letter}, "
                             f"judge = {r.judge}" + (f", human = {r.human_category}" if r.human_category else "")):
                st.write(r.summary)
                if r.judge_evidence:
                    st.caption("Judge evidence: " + str(r.judge_evidence))
        edited = st.data_editor(hc[["case", "qid", "condition", "letter", "judge", "human_category"]],
                                column_config={"human_category": st.column_config.SelectboxColumn(
                                    options=["not_mentioned", "mentioned_dismissed", "mentioned_used"])},
                                disabled=["case", "qid", "condition", "letter", "judge"], key="hc_edit",
                                width="stretch")
        if st.button("Save hand-check labels"):
            hc["human_category"] = edited["human_category"].values
            hc.to_csv(lab_path, index=False)
            st.success(f"Saved {lab_path.relative_to(ROOT)}")
        done = edited[edited.human_category.astype(bool)]
        if len(done):
            st.write(f"Judge agrees with you on {(done.judge == done.human_category).mean():.0%} of "
                     f"{len(done)} labelled cases.")

        st.subheader("All transcripts")
        f1, f2 = st.columns(2)
        rc = f1.multiselect("Conditions", cond_order(rsm.condition), key="rs_conds")
        rj = f2.multiselect("Judge category", sorted(rsm.judge.unique()), key="rs_j")
        rx = rsm[rsm.condition.isin(rc or rsm.condition.unique()) & rsm.judge.isin(rj or rsm.judge.unique())]
        st.caption(f"{len(rx)} samples (showing up to 80)")
        for r in rx.head(80).itertuples():
            with st.expander(f"{r.qid} / {r.condition} / sample {r.sample}: answered {r.letter} "
                             f"(none mode {r.none_mode}), shifted {r.shifted}, judge {r.judge}"):
                st.write(r.summary or "_(no summary returned)_")
