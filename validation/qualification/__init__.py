"""Model Qualification Harness — offline research tooling.

Specified by `docs/specs/V0_5_ACCEPTANCE_OPERATING_MODEL.md` section 4, at the
observation counts recorded in section 2.1.

This package answers "how good is this model at this job?" with no Streamlit, no
browser and no investigation database. It is **not** a product component:

- it is not a second generation call, not a semantic-adjudication boundary, and
  not a repair or retry path;
- it lives entirely outside the product's request path, so it does not weaken the
  one-call contract;
- nothing it produces may be wired into the application.

It produces no automated quality score, rubric score, or model-judged verdict of
any kind. ADR 006 rejected that class of false assurance. Semantic adequacy is
judged by the Product Owner reading every run in full.
"""
