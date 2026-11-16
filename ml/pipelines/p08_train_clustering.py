"""Stage 08 — investor behaviour clustering.

K-Means on behavioural features, with Gaussian Mixture and Agglomerative
clustering fitted alongside as comparators so the choice of K-Means is an
argued one rather than an assumption.

Evaluation goes beyond the usual internal indices. Because the cohort was
generated from known archetypes, clustering can be scored with Adjusted
Rand Index against the true generating label. That distinction matters:
silhouette says whether the clusters are *tight*, ARI says whether they are
the *right* clusters. A model can score well on the first while recovering
nothing real, and only the second can tell you.

Cluster names are assigned after inspecting the fitted centroids, never
decided in advance.

Run:  python -m ml.pipelines.p08_train_clustering
"""

from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import (
    adjusted_rand_score, calinski_harabasz_score, davies_bouldin_score,
    normalized_mutual_info_score, silhouette_score,
)
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from .common import (
    MODEL_DIR,
    PROCESSED_DIR,
    PipelineError,
    Stage,
    get_logger,
    silence_accelerate_matmul_warnings,
    write_report,
)

log = get_logger("cluster")

silence_accelerate_matmul_warnings()

RANDOM_STATE = 42
K_RANGE = range(2, 11)
BOOTSTRAP_ROUNDS = 20
BOOTSTRAP_FRACTION = 0.8

# Behavioural features only. Age and income are deliberately excluded: the
# goal is to group investors by how they *behave*, and including demographics
# would let the model cluster on who they are instead.
FEATURE_COLUMNS = [
    "equity_allocation", "etf_allocation", "gold_allocation",
    "debt_allocation", "cash_allocation", "allocation_volatility",
    "turnover", "trades_per_month", "portfolio_volatility", "max_drawdown",
    "hhi", "top_holding_weight", "n_holdings",
    "contribution_consistency", "contribution_rate",
]


def choose_k(scaled: np.ndarray, sample: np.ndarray) -> tuple[int, list[dict]]:
    """Pick K by silhouette, recording every candidate for the report."""
    results = []
    for k in K_RANGE:
        model = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE)
        labels = model.fit_predict(scaled)
        entry = {
            "k": k,
            "inertia": round(float(model.inertia_), 2),
            "silhouette": round(float(silhouette_score(scaled[sample], labels[sample])), 4),
            "davies_bouldin": round(float(davies_bouldin_score(scaled, labels)), 4),
            "calinski_harabasz": round(float(calinski_harabasz_score(scaled, labels)), 1),
        }
        results.append(entry)
        log.info("  k=%2d  silhouette %.4f  davies-bouldin %.4f  inertia %.0f",
                 k, entry["silhouette"], entry["davies_bouldin"], entry["inertia"])

    best = max(results, key=lambda r: r["silhouette"])
    return best["k"], results


def bootstrap_stability(scaled: np.ndarray, k: int, rng: np.random.Generator) -> dict:
    """How reproducible the clustering is under resampling.

    Refit on overlapping subsamples and compare labels on the shared rows.
    A high silhouette on an unstable solution means the model found a
    partition of this particular sample, not a structure in the population.
    """
    n = len(scaled)
    size = int(n * BOOTSTRAP_FRACTION)
    scores = []

    for _ in range(BOOTSTRAP_ROUNDS):
        a = rng.choice(n, size=size, replace=False)
        b = rng.choice(n, size=size, replace=False)
        shared = np.intersect1d(a, b)
        if len(shared) < 50:
            continue

        labels_a = KMeans(k, n_init=5, random_state=RANDOM_STATE).fit(scaled[a]).predict(scaled[shared])
        labels_b = KMeans(k, n_init=5, random_state=RANDOM_STATE).fit(scaled[b]).predict(scaled[shared])
        scores.append(adjusted_rand_score(labels_a, labels_b))

    return {
        "rounds": len(scores),
        "mean_ari": round(float(np.mean(scores)), 4) if scores else None,
        "std_ari": round(float(np.std(scores)), 4) if scores else None,
        "min_ari": round(float(np.min(scores)), 4) if scores else None,
    }


def describe_clusters(
    features: pd.DataFrame, labels: np.ndarray, columns: list[str]
) -> list[dict]:
    """Characterise each cluster from its centroid, then name it.

    Names are derived here, after fitting, from how each cluster actually
    differs from the cohort average.
    """
    frame = features.copy()
    frame["cluster"] = labels
    overall = frame[columns].mean()

    profiles = []
    for cluster_id, group in frame.groupby("cluster"):
        centroid = group[columns].mean()
        # Relative difference from the cohort average, in standard deviations.
        spread = frame[columns].std().replace(0, np.nan)
        deviation = ((centroid - overall) / spread).sort_values()

        traits = {
            "highest": [
                {"feature": f, "z": round(float(deviation[f]), 2)}
                for f in deviation.index[-3:][::-1]
            ],
            "lowest": [
                {"feature": f, "z": round(float(deviation[f]), 2)}
                for f in deviation.index[:3]
            ],
        }

        # Name from how the centroid actually differs from the cohort, in
        # descending order of specificity so the most distinctive trait wins.
        # The earlier version keyed on too few signals and produced three
        # clusters all called "Growth-oriented investor", which tells a user
        # nothing about what separates them.
        equity = float(centroid["equity_allocation"] + centroid["etf_allocation"])
        defensive = float(centroid["debt_allocation"] + centroid["cash_allocation"])
        turnover = float(centroid["turnover"])
        consistency = float(centroid["contribution_consistency"])
        concentration = float(centroid["top_holding_weight"])
        drift = float(centroid["allocation_volatility"])
        holdings = float(centroid["n_holdings"])

        average_turnover = float(overall["turnover"])
        average_consistency = float(overall["contribution_consistency"])
        average_concentration = float(overall["top_holding_weight"])
        average_drift = float(overall["allocation_volatility"])
        average_holdings = float(overall["n_holdings"])

        if turnover > average_turnover * 1.8:
            name = "High-turnover trader"
        elif consistency < average_consistency * 0.6 and turnover < average_turnover * 0.6:
            name = "Passive holder"
        elif defensive > 0.45:
            name = "Capital preserver"
        elif (
            centroid["etf_allocation"] > centroid["equity_allocation"]
            and consistency > average_consistency
        ):
            name = "Systematic index accumulator"
        elif equity > 0.70 and concentration > average_concentration * 1.15:
            name = "Concentrated growth seeker"
        elif equity > 0.70:
            name = "Growth-oriented investor"
        elif drift > average_drift * 1.3:
            name = "Drifting allocator"
        elif holdings > average_holdings * 1.15:
            name = "Broadly diversified investor"
        else:
            name = "Balanced investor"

        profiles.append({
            "cluster": int(cluster_id),
            "name": name,
            "size": int(len(group)),
            "share": round(len(group) / len(frame), 4),
            "centroid": {c: round(float(centroid[c]), 4) for c in columns},
            "distinguishing_traits": traits,
        })

    # Disambiguate if the heuristics produced a duplicate name.
    seen: dict[str, int] = {}
    for profile in profiles:
        base = profile["name"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            profile["name"] = f"{base} {seen[base]}"
    return profiles


def main() -> None:
    path = PROCESSED_DIR / "features_clustering.parquet"
    if not path.exists():
        raise PipelineError("run stage 07 first to build the feature tables")

    rng = np.random.default_rng(RANDOM_STATE)
    report: dict = {"random_state": RANDOM_STATE, "features": FEATURE_COLUMNS}

    with Stage(log, "load features"):
        features = pd.read_parquet(path)
        matrix = features[FEATURE_COLUMNS].copy()
        # A handful of investors have an undefined std or contribution rate.
        matrix = matrix.fillna(matrix.median())
        log.info("  %d investors x %d behavioural features", *matrix.shape)

    with Stage(log, "scale"):
        scaler = StandardScaler()
        scaled = scaler.fit_transform(matrix)
        # Silhouette on the full set is O(n^2); sample for that metric only.
        sample = rng.choice(len(scaled), size=min(5000, len(scaled)), replace=False)

    with Stage(log, "select k"):
        best_k, k_results = choose_k(scaled, sample)
        report["k_selection"] = k_results
        report["chosen_k"] = best_k
        log.info("  chosen k = %d (highest silhouette)", best_k)

    with Stage(log, "fit final model"):
        kmeans = KMeans(n_clusters=best_k, n_init=20, random_state=RANDOM_STATE)
        labels = kmeans.fit_predict(scaled)

    with Stage(log, "compare against other algorithms"):
        comparison = {}
        kmeans_silhouette = silhouette_score(scaled[sample], labels[sample])
        comparison["kmeans"] = {
            "silhouette": round(float(kmeans_silhouette), 4),
            "davies_bouldin": round(float(davies_bouldin_score(scaled, labels)), 4),
        }

        gmm = GaussianMixture(n_components=best_k, random_state=RANDOM_STATE, n_init=3)
        gmm_labels = gmm.fit_predict(scaled)
        comparison["gaussian_mixture"] = {
            "silhouette": round(float(silhouette_score(scaled[sample], gmm_labels[sample])), 4),
            "davies_bouldin": round(float(davies_bouldin_score(scaled, gmm_labels)), 4),
        }

        # Agglomerative is O(n^2) in memory; fit on a subsample.
        subset = rng.choice(len(scaled), size=min(4000, len(scaled)), replace=False)
        agglomerative_labels = AgglomerativeClustering(n_clusters=best_k).fit_predict(scaled[subset])
        comparison["agglomerative"] = {
            "silhouette": round(float(silhouette_score(scaled[subset], agglomerative_labels)), 4),
            "davies_bouldin": round(float(davies_bouldin_score(scaled[subset], agglomerative_labels)), 4),
            "note": f"fitted on a {len(subset)}-investor subsample for tractability",
        }

        for name, scores in comparison.items():
            log.info("  %-18s silhouette %.4f  davies-bouldin %.4f",
                     name, scores["silhouette"], scores["davies_bouldin"])
        report["algorithm_comparison"] = comparison

    with Stage(log, "stability under resampling"):
        stability = bootstrap_stability(scaled, best_k, rng)
        report["stability"] = stability
        log.info("  mean ARI across %d resamples: %.4f (sd %.4f, worst %.4f)",
                 stability["rounds"], stability["mean_ari"],
                 stability["std_ari"], stability["min_ari"])

    with Stage(log, "recovery of the true archetypes"):
        # Available only because the cohort is synthetic and we know the
        # generating label. This is the measure that says whether the
        # clustering found real structure.
        truth = features["archetype"].to_numpy()
        ari = adjusted_rand_score(truth, labels)
        nmi = normalized_mutual_info_score(truth, labels)
        report["archetype_recovery"] = {
            "adjusted_rand_index": round(float(ari), 4),
            "normalized_mutual_info": round(float(nmi), 4),
            "true_archetypes": int(pd.Series(truth).nunique()),
            "clusters_found": int(best_k),
            "note": (
                "Measurable only because the cohort is synthetic. ARI corrects "
                "for chance agreement: 0 is random, 1 is a perfect match. "
                "Archetypes overlap by design, so a perfect score is neither "
                "expected nor desirable."
            ),
        }
        log.info("  ARI vs true archetype: %.4f   NMI: %.4f", ari, nmi)

        crosstab = pd.crosstab(truth, labels)
        log.info("  archetype x cluster:\n%s", crosstab.to_string())
        report["archetype_recovery"]["crosstab"] = crosstab.to_dict()

    with Stage(log, "describe clusters"):
        profiles = describe_clusters(features, labels, FEATURE_COLUMNS)
        for profile in sorted(profiles, key=lambda p: -p["size"]):
            top = ", ".join(t["feature"] for t in profile["distinguishing_traits"]["highest"][:2])
            log.info("  cluster %d  %-28s %5d investors (%4.1f%%)  high: %s",
                     profile["cluster"], profile["name"], profile["size"],
                     100 * profile["share"], top)
        report["clusters"] = profiles

    with Stage(log, "save artifacts"):
        projection = PCA(n_components=2, random_state=RANDOM_STATE).fit(scaled)
        artifact = {
            "scaler": scaler,
            "kmeans": kmeans,
            "pca": projection,
            "feature_columns": FEATURE_COLUMNS,
            "cluster_profiles": profiles,
            "k": best_k,
            "version": "1.0.0",
        }
        joblib.dump(artifact, MODEL_DIR / "investor_clustering.joblib")

        assignments = features[["investor_id", "archetype"]].copy()
        assignments["cluster"] = labels
        assignments["cluster_name"] = [
            next(p["name"] for p in profiles if p["cluster"] == c) for c in labels
        ]
        coordinates = projection.transform(scaled)
        assignments["pc1"] = coordinates[:, 0]
        assignments["pc2"] = coordinates[:, 1]
        assignments.to_parquet(PROCESSED_DIR / "cluster_assignments.parquet", index=False)
        log.info("  → ml/models/investor_clustering.joblib")

    write_report("clustering", report)
    log.info("clustering report written")


if __name__ == "__main__":
    main()
