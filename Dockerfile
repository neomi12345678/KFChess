# Server-only image: server/ never imports client/ or view/ (see README.md's
# "Architecture" section), so this installs server/requirements.txt - not
# the root requirements.txt, which is the GUI/client dependency list
# (opencv-python) this image has no use for.
FROM python:3.11-slim

WORKDIR /app

COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

# The composition root (server/main.py) reaches across every layer it
# wires together (model/, rules/, physics/, realtime/, engine/, boardio/,
# events/, protocol/, server/ - see README.md), so the whole tree is
# needed, not just server/.
COPY model/ model/
COPY rules/ rules/
COPY physics/ physics/
COPY realtime/ realtime/
COPY engine/ engine/
COPY boardio/ boardio/
COPY events/ events/
COPY protocol/ protocol/
COPY server/ server/
COPY logic_config.py .
COPY frame_clock.py .

EXPOSE 8765

CMD ["python", "-m", "server.main"]
