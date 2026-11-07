from fastapi import APIRouter, Request, Response, status

from aivee_api.auth.deps import COOKIE, CurrentUser, clear_session_cookie, set_session_cookie
from aivee_api.auth.schemas import LoginIn, Me, RegisterIn, me_out
from aivee_api.auth.service import AuthService
from aivee_api.deps import Services, ServicesDep, SessionDep

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _service(s: SessionDep, svc: Services) -> AuthService:
    return AuthService(s, svc.settings, svc.login_limiter)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, response: Response, s: SessionDep, svc: ServicesDep) -> Me:
    """Create an organization and its owner, and log the owner in."""
    principal, token = await _service(s, svc).register(
        data.org_name, data.name, data.email, data.password
    )
    set_session_cookie(response, token, svc.settings)
    return me_out(principal)


@router.post("/login")
async def login(data: LoginIn, response: Response, s: SessionDep, svc: ServicesDep) -> Me:
    principal, token = await _service(s, svc).login(data.email, data.password)
    set_session_cookie(response, token, svc.settings)
    return me_out(principal)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, s: SessionDep, svc: ServicesDep) -> Response:
    await _service(s, svc).logout(request.cookies.get(COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, svc.settings)
    return response


@router.get("/me")
async def me(principal: CurrentUser) -> Me:
    return me_out(principal)
