FROM python:3.12-slim

RUN useradd --create-home --shell /usr/sbin/nologin bridge

WORKDIR /home/bridge

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./

USER bridge

EXPOSE 8010

CMD ["python", "app.py"]
