from __future__ import annotations

import json
import os
import stat
import time
import typing
from abc import abstractmethod
from email.utils import formatdate
from mimetypes import guess_type
from urllib.parse import quote

import anyio
import anyio.to_thread
from anyio._core._fileio import AnyStr
from starlette._compat import md5_hexdigest
from starlette.background import BackgroundTask
from starlette.concurrency import iterate_in_threadpool
from starlette.responses import Response
from starlette.types import Receive, Scope, Send


def slicer(text: typing.Union[str, bytes], chunk_size: int):
    return (text[chunk_index : chunk_index + chunk_size] for chunk_index in range(0, len(text), chunk_size))


class BaseFileResponse(Response):
    chunk_size = 64 * 1024

    @abstractmethod
    async def iterate_content(self, content_size: int) -> typing.Iterable[AnyStr]: ...

    async def pre_call(self) -> None: ...

    async def post_call(self) -> None: ...

    def __init__(
        self,
        status_code: int = 200,
        headers: typing.Optional[typing.Mapping[str, str]] = None,
        media_type: typing.Optional[str] = None,
        background: typing.Optional[BackgroundTask] = None,
        filename: typing.Optional[str] = None,
        size: typing.Optional[int] = None,
        mtime: typing.Optional[float] = None,
        content_disposition_type: str = 'attachment',
    ) -> None:
        if media_type is None and filename is not None:
            media_type = guess_type(filename)[0] or 'text/plain'

        self.status_code = status_code
        self.media_type = media_type
        self.background = background

        self.filename = filename

        self.init_headers(headers)
        self.size = size
        self.mtime = mtime

        if self.filename is not None:
            self.set_content_disposition_header(content_disposition_type=content_disposition_type)

    def set_content_disposition_header(self, content_disposition_type: str) -> None:
        content_disposition_filename = quote(self.filename)
        if content_disposition_filename != self.filename:
            content_disposition = f"{content_disposition_type}; filename*=utf-8''{content_disposition_filename}"
        else:
            content_disposition = f'{content_disposition_type}; filename="{self.filename}"'
        self.headers.setdefault('content-disposition', content_disposition)

    def set_stat_headers(self, size: int, mtime: float) -> None:
        content_length = str(size)
        last_modified = formatdate(mtime, usegmt=True)
        etag_base = str(mtime) + '-' + str(size)
        etag = f'"{md5_hexdigest(etag_base.encode(), usedforsecurity=False)}"'

        self.headers.setdefault('content-length', content_length)
        self.headers.setdefault('last-modified', last_modified)
        self.headers.setdefault('etag', etag)

    async def __call__(self, scope: Scope, _: Receive, send: Send) -> None:
        await self.pre_call()
        await send({
            'type': 'http.response.start',
            'status': self.status_code,
            'headers': self.raw_headers,
        })
        if scope['method'].upper() == 'HEAD':
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
        else:
            content_iterator = self.iterate_content(self.chunk_size)

            if not isinstance(content_iterator, typing.AsyncIterable):
                content_iterator = iterate_in_threadpool(content_iterator)

            more_body = True
            async for chunk in content_iterator:
                more_body = len(chunk) == self.chunk_size
                await send({
                    'type': 'http.response.body',
                    'body': chunk,
                    'more_body': more_body,
                })
        await self.post_call()
        if self.background is not None:
            await self.background()


class FileResponse(BaseFileResponse):
    def __init__(
        self,
        path: typing.Union[str, os.PathLike[str]],
        status_code: int = 200,
        headers: typing.Optional[typing.Mapping[str, str]] = None,
        media_type: typing.Optional[str] = None,
        background: typing.Optional[BackgroundTask] = None,
        filename: typing.Optional[str] = None,
        stat_result: typing.Optional[os.stat_result] = None,
        content_disposition_type: str = 'attachment',
    ) -> None:
        if media_type is None and filename is None:
            media_type = guess_type(path)[0]

        size = None
        mtime = None

        if stat_result is not None:
            size = stat_result.st_size
            mtime = stat_result.st_mtime

        super().__init__(
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
            filename=filename,
            size=size,
            mtime=mtime,
            content_disposition_type=content_disposition_type,
        )

        self.path = path
        self.stat_result = stat_result

    async def pre_call(self) -> None:
        stat_result = self.stat_result
        if stat_result is None:
            try:
                stat_result = await anyio.to_thread.run_sync(os.stat, self.path)
                self.set_stat_headers(stat_result.st_size, stat_result.st_mtime)
            except FileNotFoundError as exc:
                message = f'File at path {self.path} does not exist.'
                raise RuntimeError(message) from exc

        mode = stat_result.st_mode
        if not stat.S_ISREG(mode):
            message = f'File at path {self.path} is not a file.'
            raise RuntimeError(message)

    async def iterate_content(self, chunk_size: int) -> typing.Iterable[AnyStr]:
        async with await anyio.open_file(self.path, mode='rb') as file:
            yield await file.read(chunk_size)


class BytesFileResponse(BaseFileResponse):
    def __init__(
        self,
        content: bytes,
        filename: str,
        status_code: int = 200,
        headers: typing.Optional[typing.Mapping[str, str]] = None,
        media_type: typing.Optional[str] = None,
        background: typing.Optional[BackgroundTask] = None,
        size: typing.Optional[int] = None,
        mtime: typing.Optional[float] = None,
        content_disposition_type: str = 'attachment',
    ) -> None:
        super().__init__(
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
            filename=filename,
            size=size,
            mtime=mtime,
            content_disposition_type=content_disposition_type,
        )
        self.content = content

    async def pre_call(self) -> None:
        size = self.size
        mtime = self.mtime

        if size is None:
            size = len(self.content)

        if mtime is None:
            mtime = time.monotonic()

        self.set_stat_headers(self.size or len(self.content), self.mtime or time.monotonic())

    def iterate_content(self, chunk_size: int) -> typing.Iterable[AnyStr]:
        yield from slicer(self.content, chunk_size)


class TextFileResponse(BaseFileResponse):
    def __init__(
        self,
        content: str,
        filename: str,
        status_code: int = 200,
        headers: typing.Optional[typing.Mapping[str, str]] = None,
        media_type: typing.Optional[str] = None,
        background: typing.Optional[BackgroundTask] = None,
        size: typing.Optional[int] = None,
        mtime: typing.Optional[float] = None,
        content_disposition_type: str = 'attachment',
    ) -> None:
        super().__init__(
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
            filename=filename,
            size=size,
            mtime=mtime,
            content_disposition_type=content_disposition_type,
        )
        self.content = content.encode(self.charset)

    async def pre_call(self) -> None:
        size = self.size
        mtime = self.mtime

        if size is None:
            size = len(self.content)

        if mtime is None:
            mtime = time.monotonic()

        self.set_stat_headers(self.size or len(self.content), self.mtime or time.monotonic())

    def iterate_content(self, chunk_size: int) -> typing.Iterable[AnyStr]:
        yield from slicer(self.content, chunk_size)


class JsonFileResponse(BytesFileResponse):
    def __init__(
        self,
        content: typing.Union[dict[str, typing.Any], list[typing.Any]],
        filename: str,
        status_code: int = 200,
        headers: typing.Optional[typing.Mapping[str, str]] = None,
        media_type: typing.Optional[str] = None,
        background: typing.Optional[BackgroundTask] = None,
        size: typing.Optional[int] = None,
        mtime: typing.Optional[float] = None,
        content_disposition_type: str = 'attachment',
    ) -> None:
        content = json.dumps(content).encode(self.charset)
        super().__init__(
            content=content,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
            filename=filename,
            size=size,
            mtime=mtime,
            content_disposition_type=content_disposition_type,
        )
