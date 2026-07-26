# GitHub, Railway, and Connector Workflow

GitHub holds reviewed source changes. Use feature branches and pull requests; never push directly to `Master`. Railway deployment triggers must be intentionally restricted: a controlled staging branch or preview environment may deploy to staging, while production requires the reviewed merge commit and successful readiness checks.

Firecrawl is an optional final retrieval adapter. Public structured endpoints and direct HTTP adapters remain preferred where configured. Missing optional connector configuration must not alter core data quality or fabricate a healthy state.

Keep connector credentials in local environment configuration or Railway variables only. Never commit them or print them in reports.
