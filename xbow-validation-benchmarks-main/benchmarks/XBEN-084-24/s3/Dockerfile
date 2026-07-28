FROM node:20-alpine

RUN apk --no-cache add curl
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci || npm install
COPY . .
RUN chown -R node:node /app && chmod -R 0755 /app
EXPOSE 8333
USER node
CMD [ "npm", "start" ]