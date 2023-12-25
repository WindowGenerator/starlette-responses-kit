import json
from typing import AsyncIterator, Callable

import anyio
import pytest
from starlette import status
from starlette.background import BackgroundTask
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from starlette_responses_kit.file import BytesFileResponse, JsonFileResponse, TextFileResponse

TestClientFactory = Callable[..., TestClient]


@pytest.mark.parametrize(
    'content,response_klass,response_content',
    [
        (
            b'<file content>' * 1000,
            BytesFileResponse,
            b'<file content>' * 1000,
        ),
        (
            '<file content>' * 1000,
            TextFileResponse,
            b'<file content>' * 1000,
        ),
        (
            {key: '<file content>' for key in range(1000)},
            JsonFileResponse,
            json.dumps({key: '<file content>' for key in range(1000)}).encode('utf-8'),
        ),
    ],
)
def test_custom_file_response(
    content, response_klass, response_content, test_client_factory: TestClientFactory
) -> None:
    filled_by_bg_task = ''

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        async def numbers(minimum: int, maximum: int) -> AsyncIterator[str]:
            for i in range(minimum, maximum + 1):
                yield str(i)
                if i != maximum:
                    yield ', '
                await anyio.sleep(0)

        async def numbers_for_cleanup(start: int = 1, stop: int = 5) -> None:
            nonlocal filled_by_bg_task
            async for thing in numbers(start, stop):
                filled_by_bg_task = filled_by_bg_task + thing

        cleanup_task = BackgroundTask(numbers_for_cleanup, start=6, stop=9)

        response = response_klass(content, filename='example.png', background=cleanup_task)
        await response(scope, receive, send)

    assert filled_by_bg_task == ''
    client = test_client_factory(app)
    response = client.get('/')
    expected_disposition = 'attachment; filename="example.png"'
    assert response.status_code == status.HTTP_200_OK
    assert response.content == response_content
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['content-disposition'] == expected_disposition
    assert 'content-length' in response.headers
    assert 'last-modified' in response.headers
    assert 'etag' in response.headers
    assert filled_by_bg_task == '6, 7, 8, 9'


@pytest.mark.parametrize(
    'content,response_klass,response_content',
    [
        (
            b'<file content>' * 1000,
            BytesFileResponse,
            b'<file content>' * 1000,
        ),
        (
            '<file content>' * 1000,
            TextFileResponse,
            b'<file content>' * 1000,
        ),
        (
            {key: 'привет' for key in range(1000)},
            JsonFileResponse,
            json.dumps({key: 'привет' for key in range(1000)}).encode('utf-8'),
        ),
    ],
)
def test_custom_file_response_known_size(
    content, response_klass, response_content, test_client_factory: TestClientFactory
) -> None:
    app = response_klass(content, filename='example.png')
    client: TestClient = test_client_factory(app)
    response = client.get('/')
    assert response.headers['content-length'] == str(len(response_content))
