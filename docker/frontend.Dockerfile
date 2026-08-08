# Development image for the UrbanPulse GIS command centre.
#
# Development-only: it runs `next dev` with the source bind-mounted. A
# production image would use a multi-stage build ending in `next start` over
# the standalone output; that is Phase 6 work and is not pretended here.
FROM node:22-slim

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

# Install dependencies from the lockfile first so this layer caches across
# source edits.
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
