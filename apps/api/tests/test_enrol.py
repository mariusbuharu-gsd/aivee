import math
from typing import Any

from aivee_api.staff.enrol import Enroller, Upload


def test_photos_give_one_normalised_embedding_each(fake_enroller: Enroller) -> None:
    result = fake_enroller.enrol(
        [Upload("a.jpg", "image/jpeg", bytes([2])), Upload("b.png", "image/png", bytes([4]))]
    )
    assert (result.frames, result.crops, len(result.embeddings)) == (2, 2, 2)
    for vec in result.embeddings:
        assert len(vec) == 512
        assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0)


def test_photo_without_a_person_is_embedded_whole(fake_enroller: Enroller) -> None:
    # e.g. a T-shirt on a hanger: the cropper finds nobody in odd frames
    result = fake_enroller.enrol([Upload("tshirt.jpg", "image/jpeg", bytes([3]))])
    assert len(result.embeddings) == 1
    assert result.skipped == []


def test_video_uses_every_frame_with_a_person(fake_enroller: Enroller) -> None:
    result = fake_enroller.enrol([Upload("clip.mp4", "video/mp4", bytes([1, 2, 3, 4, 6]))])
    assert result.frames == 5
    assert result.crops == 3


def test_video_without_people_is_reported(fake_enroller: Enroller) -> None:
    result = fake_enroller.enrol([Upload("empty.mp4", "video/mp4", bytes([1, 3]))])
    assert result.embeddings == []
    assert result.skipped == ["empty.mp4"]


def test_multiple_people_in_one_frame() -> None:
    class Decoder:
        def frames(self, upload: Upload) -> list[Any]:
            return [0]

    class TwoPeople:
        def crops(self, frame: Any) -> list[Any]:
            return [1, 2]

    class Embed:
        def embed(self, crop: Any) -> list[float]:
            return [float(crop), 0.0]

    result = Enroller(Decoder(), TwoPeople(), Embed()).enrol([Upload("g.jpg", "image/jpeg", b"x")])
    assert result.embeddings == [[1.0, 0.0], [1.0, 0.0]]
