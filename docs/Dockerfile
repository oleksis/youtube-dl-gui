FROM ruby:3.2-slim-bullseye as jekyll
# https://github.com/BretFisher/jekyll-serve/blob/main/Dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 4000

WORKDIR /site

COPY wiki/Gemfile .

RUN gem install bundler jekyll \
    && bundle install --retry 5 --jobs 20

CMD [ "bundle", "exec", "jekyll", "serve", "--force_polling", "-H", "0.0.0.0", "-P", "4000" ]
