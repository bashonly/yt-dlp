from pathlib import Path

import pytest

from yt_dlp.downloader.sabr._state import (
    SabrState,
    SabrStateFile,
    SabrStateInitSegment,
    SabrStateSegment,
    SabrStateSequence,
)
from yt_dlp.extractor.youtube._proto.videostreaming import FormatId


@pytest.fixture
def sabr_state():
    return SabrState(
        format_id=FormatId(itag=251, lmt=123456789, xtags='dash'),
        init_segment=SabrStateInitSegment(content_length=1024),
        sequences=[
            SabrStateSequence(
                sequence_start_number=1,
                sequence_content_length=4096,
                first_segment=SabrStateSegment(
                    sequence_number=1,
                    start_time_ms=0,
                    duration_ms=1000,
                    duration_estimated=False,
                    content_length=2048,
                ),
                last_segment=SabrStateSegment(
                    sequence_number=2,
                    start_time_ms=1000,
                    duration_ms=1000,
                    duration_estimated=True,
                    content_length=2048,
                ),
            ),
        ],
        broadcast_id='broadcast-1',
    )


class TestSabrStateFile:
    def test_update(self, fd, filename, sabr_state):
        state_file = SabrStateFile(filename, fd)

        assert state_file.filename == filename + '.state'
        assert state_file.exists is False
        assert Path(state_file.filename).exists() is False

        state_file.update(sabr_state)

        assert state_file.exists is True
        assert Path(state_file.filename).exists() is True
        assert state_file.retrieve() == sabr_state

        state_file.remove()

        assert state_file.exists is False
        assert Path(state_file.filename).exists() is False

    def test_fresh_retrieve(self, fd, filename, sabr_state):
        state_file = SabrStateFile(filename, fd)
        state_file.update(sabr_state)

        # retrieve state file using another instance
        retrieve_state_file = SabrStateFile(filename, fd)
        assert retrieve_state_file.exists is True
        assert Path(retrieve_state_file.filename).exists() is True
        assert retrieve_state_file.retrieve() == sabr_state
        state_file.remove()
        assert state_file.exists is False
        assert Path(state_file.filename).exists() is False
