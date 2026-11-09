# Deploy ODB SHADY 6.9

This repository includes a Render Blueprint in `render.yaml`. It creates one small Python web service that serves the landing page and authenticated chat API from the same HTTPS origin.

## Before deploying

You need:
- An API key from the model provider you choose.
- A model identifier enabled for that API key.
- A private owner access token at least 32 characters long.

Generate a strong owner token on a trusted device:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never paste either secret into GitHub files, chat messages, or source code.

## Deploy

1. Sign in to Render and choose **New → Blueprint**.
2. Select the public repository `dotsond873/ODB-SHADY-6.9`.
3. Review the service from `render.yaml`.
4. In the service's Environment settings, set the private values for `SHADY_ACCESS_TOKEN`, `SHADY_API_KEY`, and `SHADY_MODEL`. Keep them secret.
5. Deploy the service.
6. Open its HTTPS URL. Select **Enter ODB SHADY 6.9**, enter the owner token, and send a short test message.

The model provider may charge for usage. Render hosting may also have plan limits or charges; review the current plan and any paid add-ons before confirming deployment.

## Storage warning

The starter Blueprint uses a free web-service plan and does not attach a persistent disk. Its local SQLite memory database can be lost when the service restarts, redeploys, or is recycled. Treat this as a test deployment only until persistent storage and backups are configured. A persistent Render disk generally requires a paid service plan; do not enable one without reviewing and approving its cost.

## Security boundary

The chat API requires the owner bearer token. Use the HTTPS URL supplied by Render, do not share the owner token, and rotate it if it is exposed. The owner token is a single-owner gate, not a multi-user account system. The model can answer chat messages but does not receive unrestricted shell or server access.

## Health check

Render checks `/api/health`. The endpoint reports service health and whether a model provider was configured; it never returns credentials.
