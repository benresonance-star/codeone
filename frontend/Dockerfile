FROM node:20-alpine

WORKDIR /app

COPY frontend/package.json /app/package.json
COPY frontend/package-lock.json /app/package-lock.json
COPY frontend/tsconfig.json /app/tsconfig.json
COPY frontend/next-env.d.ts /app/next-env.d.ts
COPY frontend/next.config.mjs /app/next.config.mjs
COPY frontend/app /app/app
COPY frontend/components /app/components
COPY frontend/lib /app/lib

RUN npm install
RUN npm run build

ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "run", "start"]
