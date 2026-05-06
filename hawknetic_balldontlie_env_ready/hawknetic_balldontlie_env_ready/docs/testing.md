# Testing

Run the test suite:

```bash
pytest -q
```

Current coverage focuses on the user-critical path:
- landing page renders
- lead capture works
- register and login flow works
- local checkout activates a subscription
- account cancellation works
- AI endpoint enforces opt-in and returns a response
