"""Integration tests for the scrape orchestration flow.

These tests require a running PostgreSQL database (run via Docker Compose).

Note: The old monolithic run_scrape shim was removed in PLAN_005 Task 1.
The detailed insert/upsert/freshness tests live in test_orchestrator_phases.py.
"""
