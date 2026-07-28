FROM node:20-alpine

RUN apk --no-cache add curl

WORKDIR /app
COPY . .
COPY .env.example .env
RUN npm install

ARG FLAG
RUN sed -i "s/@FLAG@/${FLAG}/g" .env

RUN npm run build
EXPOSE 3000

CMD ["npm", "start"]