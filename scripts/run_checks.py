"""Run the capstone's offline regression tests without live provider calls.

Live integration commands (budget gates and Gemini connection checks) are
deliberately excluded. Test fixtures use temporary files and isolated SQLite
databases; provider calls and production database sessions are substituted.
"""

import unittest
import warnings


OFFLINE_MODULES = (
    "scripts.check_api_inputs",
    "scripts.check_image_downloads",
    "scripts.check_image_source_sync",
    "scripts.check_fresh_postgres_safety",
    "scripts.check_interrupted_job_recovery",
    "scripts.check_bear_subtype_guard",
    "scripts.check_budget",
    "scripts.check_confidence_guard",
    "scripts.check_context_combination",
    "scripts.check_context_guard",
    "scripts.check_cutoff_study",
    "scripts.check_dog_breed_guard",
    "scripts.check_embedding_jobs",
    "scripts.check_embedding_vectors",
    "scripts.check_embedding_worker",
    "scripts.check_equivalent_concept_probe",
    "scripts.check_evaluation_datasets",
    "scripts.check_evaluation_metrics",
    "scripts.check_habitat_guard",
    "scripts.check_low_confidence_pipeline",
    "scripts.check_mismatch_guard",
    "scripts.check_no_match_api",
    "scripts.check_post_embedding_batch",
    "scripts.check_retries",
    "scripts.check_review_api",
    "scripts.check_review_processing",
    "scripts.check_selection",
    "scripts.check_similarity",
    "scripts.check_similarity_guard",
    "scripts.check_subject_aliases",
    "scripts.check_subject_guard",
    "scripts.check_tenant_read_api",
)


def main() -> int:
    # Fail if the UTC timestamp regression reappears; keep other warnings visible.
    warnings.filterwarnings(
        "error",
        message=r"datetime\.datetime\.utcnow\(\) is deprecated",
        category=DeprecationWarning,
    )
    suite = unittest.defaultTestLoader.loadTestsFromNames(OFFLINE_MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
