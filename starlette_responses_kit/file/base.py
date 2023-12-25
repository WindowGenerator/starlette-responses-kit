import os
import io
import stat
from typing import Optional, Mapping, Union
import warnings
from email.utils import formatdate
from mimetypes import guess_type
from urllib.parse import quote
import anyio
import anyio.to_thread

from starlette._compat import md5_hexdigest
from starlette.responses import Response
from starlette.background import BackgroundTask
from starlette.types import Receive, Scope, Send

    

class BaseFileResponse(Response):
    chunk_size = 64 * 1024

    def init(
        self,
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        media_type: str = "text/plain",
        background: Optional[BackgroundTask] = None,
        filename: Optional[str] = None,
        size: Optional[int] = None,
        mtime: Optional[float] = None,
        method: Optional[str] = None,
        content_disposition_type: str = "attachment",
    ) -> None:
        self.status_code = status_code
        self.filename = filename
        if method is not None:
            warnings.warn(
                "The 'method' parameter is not used, and it will be removed.",
                DeprecationWarning,
            )
        if filename is not None:
            self.media_type = guess_type(filename)[0]
        self.media_type = media_type
        self.background = background
        self.content_disposition_type = content_disposition_type
        self.init_headers(headers)
        self.size = size
        self.mtime = mtime
        if size is not None and mtime is not None:
            self.set_stat_headers(size, mtime)
    
    def set_content_disposition(self) -> None:
        content_disposition_filename = quote(self.filename)
        if content_disposition_filename != self.filename:
            content_disposition = "{}; filename*=utf-8''{}".format(
                self.content_disposition_type, content_disposition_filename
            )
        else:
            content_disposition = '{}; filename="{}"'.format(
                self.content_disposition_type, self.filename
            )
        self.headers.setdefault("content-disposition", content_disposition)

    def set_stat_headers(self, size: int, mtime: float) -> None:
        content_length = str(size)
        last_modified = formatdate(mtime, usegmt=True)
        etag_base = str(mtime) + "-" + str(size)
        etag = f'"{md5_hexdigest(etag_base.encode(), usedforsecurity=False)}"'

        if self.filename is not None:
            self.set_content_disposition()
        self.headers.setdefault("content-length", content_length)
        self.headers.setdefault("last-modified", last_modified)
        self.headers.setdefault("etag", etag)
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        raise NotImplementedError("Call should be implemented")



class BytesFileResponse(BaseFileResponse):
    def __init__(
        self,
        bytes_: Union[bytes, io.BytesIO],
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        media_type: Optional[str] = None,
        background: Optional[BackgroundTask] = None,
        filename: Optional[str] = None,
        size: Optional[int] = None,
        mtime: Optional[float] = None,
        method: Optional[str] = None,
        content_disposition_type: str = "attachment",
    ) -> None:
        self.bytes_ = bytes_
        self.init(
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
            filename=filename,
            size=size,
            mtime=mtime,
            method=method,
            content_disposition_type=content_disposition_type

        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.size is not None and self.mtime is not None:
            try:
                stat_result = await anyio.to_thread.run_sync(os.stat, self.path)
                self.set_stat_headers(stat_result.st_size, stat_result.st_mtime)
            except FileNotFoundError:
                raise RuntimeError(f"File at path {self.path} does not exist.")
            else:
                mode = stat_result.st_mode
                if not stat.S_ISREG(mode):
                    raise RuntimeError(f"File at path {self.path} is not a file.")
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": self.raw_headers,
            }
        )
        if scope["method"].upper() == "HEAD":
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        else:
            async with await anyio.open_file(self.path, mode="rb") as file:
                more_body = True
                while more_body:
                    chunk = await file.read(self.chunk_size)
                    more_body = len(chunk) == self.chunk_size
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": more_body,
                        }
                    )
        if self.background is not None:
            await self.background()