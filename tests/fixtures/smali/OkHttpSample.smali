.class public Lcom/example/api/OkHttpService;
.super Ljava/lang/Object;
.source "OkHttpService.java"

# direct methods
.method public constructor <init>()V
    .locals 0
    invoke-direct {p0}, Ljava/lang/Object;-><init>()V
    return-void
.end method

# virtual methods
.method public makeRequest(Ljava/lang/String;)V
    .locals 3

    .line 10
    new-instance v0, Lokhttp3/Request$Builder;
    invoke-direct {v0}, Lokhttp3/Request$Builder;-><init>()V

    .line 11
    const-string v1, "https://api.example.com/v1/data"
    invoke-virtual {v0, v1}, Lokhttp3/Request$Builder;->url(Ljava/lang/String;)Lokhttp3/Request$Builder;
    move-result-object v0

    .line 12
    const-string v1, "Authorization"
    const-string v2, "Bearer token"
    invoke-virtual {v0, v1, v2}, Lokhttp3/Request$Builder;->addHeader(Ljava/lang/String;Ljava/lang/String;)Lokhttp3/Request$Builder;
    move-result-object v0

    .line 13
    const-string v1, "X-Client-ID"
    invoke-virtual {v0, v1, p1}, Lokhttp3/Request$Builder;->addHeader(Ljava/lang/String;Ljava/lang/String;)Lokhttp3/Request$Builder;
    move-result-object v0

    .line 14
    invoke-virtual {v0}, Lokhttp3/Request$Builder;->get()Lokhttp3/Request$Builder;
    move-result-object v0

    .line 15
    invoke-virtual {v0}, Lokhttp3/Request$Builder;->build()Lokhttp3/Request;
    move-result-object v0

    .line 17
    return-void
.end method
