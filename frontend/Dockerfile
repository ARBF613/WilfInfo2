FROM node:20-alpine AS css
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/tailwind.config.js ./
COPY frontend/src/tailwind-input.css ./src/tailwind-input.css
ENV BROWSERSLIST_IGNORE_OLD_DATA=1
RUN npm run build:css

FROM nginx:alpine

COPY frontend/index.html /usr/share/nginx/html/index.html
COPY --from=css /build/frontend/tailwind.css /usr/share/nginx/html/tailwind.css

EXPOSE 80
