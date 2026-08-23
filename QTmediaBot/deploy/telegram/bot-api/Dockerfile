FROM alpine:3.21.7 AS build

ARG TELEGRAM_BOT_API_COMMIT=adfd7f6a8e990272851777eeb3ae0def4216f161
ARG TELEGRAM_BOT_API_IDLE_TIMEOUT_SECONDS=7200

RUN apk add --no-cache \
      alpine-sdk \
      cmake \
      gperf \
      git \
      linux-headers \
      openssl-dev \
      zlib-dev

WORKDIR /src/telegram-bot-api

RUN git init \
    && git remote add origin https://github.com/tdlib/telegram-bot-api.git \
    && git fetch --depth 1 origin "${TELEGRAM_BOT_API_COMMIT}" \
    && git checkout --detach FETCH_HEAD \
    && git submodule update --init --recursive --depth 1 \
    && test "$(grep -c 'static constexpr td::int32 IDLE_TIMEOUT = 500;' telegram-bot-api/HttpServer.h)" -eq 1 \
    && sed -i "s/static constexpr td::int32 IDLE_TIMEOUT = 500;/static constexpr td::int32 IDLE_TIMEOUT = ${TELEGRAM_BOT_API_IDLE_TIMEOUT_SECONDS};/" telegram-bot-api/HttpServer.h \
    && grep -q "static constexpr td::int32 IDLE_TIMEOUT = ${TELEGRAM_BOT_API_IDLE_TIMEOUT_SECONDS};" telegram-bot-api/HttpServer.h

RUN cmake -S . -B build \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/src/telegram-bot-api \
    && cmake --build build --target install --parallel "$(nproc)" \
    && strip bin/telegram-bot-api

FROM aiogram/telegram-bot-api:10.2@sha256:6706cc91b0d630b90e246567c1735e13c0cc152f5832e79db708d6c6de4dff3f

COPY --from=build /src/telegram-bot-api/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

LABEL org.opencontainers.image.source="https://github.com/tdlib/telegram-bot-api" \
      org.opencontainers.image.revision="adfd7f6a8e990272851777eeb3ae0def4216f161" \
      qtmedia.telegram-bot-api.idle-timeout-seconds="7200"
