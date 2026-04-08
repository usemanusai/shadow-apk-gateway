.class public interface abstract Lcom/shadow/test/api/ApiService;
.super Ljava/lang/Object;

# annotations
.annotation system Ldalvik/annotation/EnclosingClass;
    value = Lcom/shadow/test/api/ApiService;
.end annotation


# ── POST /api/v1/auth/login ──
.method public abstract login(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/Object;
    .annotation runtime Lretrofit2/http/POST;
        value = "/api/v1/auth/login"
    .end annotation

    .annotation system Ldalvik/annotation/MethodParameters;
        accessFlags = {}
        names = {
            "username",
            "password"
        }
    .end annotation

    .param p1    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Field;
            value = "username"
        .end annotation
    .end param

    .param p2    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Field;
            value = "password"
        .end annotation
    .end param
.end method


# ── GET /api/v1/users/{user_id}/profile ──
.method public abstract getUserProfile(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/Object;
    .annotation runtime Lretrofit2/http/GET;
        value = "/api/v1/users/{user_id}/profile"
    .end annotation

    .annotation system Ldalvik/annotation/MethodParameters;
        accessFlags = {}
        names = {
            "user_id",
            "Authorization"
        }
    .end annotation

    .param p1    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Path;
            value = "user_id"
        .end annotation
    .end param

    .param p2    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Header;
            value = "Authorization"
        .end annotation
    .end param
.end method


# ── PUT /api/v1/users/{user_id}/settings ──
.method public abstract updateSettings(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)Ljava/lang/Object;
    .annotation runtime Lretrofit2/http/PUT;
        value = "/api/v1/users/{user_id}/settings"
    .end annotation

    .annotation system Ldalvik/annotation/MethodParameters;
        accessFlags = {}
        names = {
            "user_id",
            "Authorization",
            "body"
        }
    .end annotation

    .param p1    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Path;
            value = "user_id"
        .end annotation
    .end param

    .param p2    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Header;
            value = "Authorization"
        .end annotation
    .end param

    .param p3    # Ljava/lang/Object;
        .annotation runtime Lretrofit2/http/Body;
        .end annotation
    .end param
.end method


# ── DELETE /api/v1/users/{user_id}/sessions/{session_id} ──
.method public abstract deleteSession(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)Ljava/lang/Object;
    .annotation runtime Lretrofit2/http/DELETE;
        value = "/api/v1/users/{user_id}/sessions/{session_id}"
    .end annotation

    .annotation system Ldalvik/annotation/MethodParameters;
        accessFlags = {}
        names = {
            "user_id",
            "session_id",
            "Authorization"
        }
    .end annotation

    .param p1    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Path;
            value = "user_id"
        .end annotation
    .end param

    .param p2    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Path;
            value = "session_id"
        .end annotation
    .end param

    .param p3    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Header;
            value = "Authorization"
        .end annotation
    .end param
.end method
