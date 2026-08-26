FROM python:3.11

RUN apt-get update
RUN apt-get install tor -y
RUN /usr/local/bin/python -m pip install --upgrade pip
WORKDIR /usr/project
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install -U dateparser
RUN chmod +x /usr/project/run_flow.sh
ENV PORT=5000

CMD ["sh", "run_flow.sh"]

