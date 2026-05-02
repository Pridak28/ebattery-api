# Production deploy is Netlify static (publish: out/). This Dockerfile is
# only for local Docker dev. The Next.js app uses `output: 'export'`, so
# we build with `npm run build` (which writes to out/) and serve statically.
FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Tiny static-server runtime
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
RUN npm install -g serve@14

COPY --from=builder /app/out ./out

EXPOSE 3000
CMD ["serve", "-s", "out", "-l", "3000"]
