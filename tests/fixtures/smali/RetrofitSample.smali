.class public interface abstract Lcom/example/api/RetrofitService;
.super Ljava/lang/Object;
.source "RetrofitService.java"

# annotations
.annotation system Ldalvik/annotation/MemberClasses;
    value = {
        Lcom/example/api/RetrofitService$DefaultImpls;
    }
.end annotation

# virtual methods
.method public abstract getUserProfile(Ljava/lang/String;)Ljava/lang/Object;
    .param p1    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Path;
            value = "userId"
        .end annotation
    .end param
    .annotation system Ldalvik/annotation/Signature;
        value = {
            "(",
            "Ljava/lang/String;",
            ")",
            "Ljava/lang/Object;"
        }
    .end annotation

    .annotation runtime Lretrofit2/http/GET;
        value = "/api/v1/users/{userId}/profile"
    .end annotation
.end method

.method public abstract updateSettings(Ljava/lang/String;Ljava/util/Map;)Ljava/lang/Object;
    .param p1    # Ljava/lang/String;
        .annotation runtime Lretrofit2/http/Header;
            value = "Authorization"
        .end annotation
    .end param
    .param p2    # Ljava/util/Map;
        .annotation runtime Lretrofit2/http/Body;
        .end annotation
    .end param
    .annotation runtime Lretrofit2/http/POST;
        value = "/api/v1/settings/update"
    .end annotation
.end method
