.class public Lcom/example/api/UserService;
.super Ljava/lang/Object;

# Retrofit API interface for user management

.method public abstract getUsers()Ljava/lang/Object;
    .annotation system Lretrofit2/http/GET;
        value = "/api/v1/users"
    .end annotation
.end method

.method public abstract getUserById(Ljava/lang/String;)Ljava/lang/Object;
    .annotation system Lretrofit2/http/GET;
        value = "/api/v1/users/{user_id}"
    .end annotation

    .annotation system Lretrofit2/http/Path;
        value = "user_id"
    .end annotation
.end method

.method public abstract createUser(Lcom/example/models/User;)Ljava/lang/Object;
    .annotation system Lretrofit2/http/POST;
        value = "/api/v1/users"
    .end annotation

    .annotation system Lretrofit2/http/Body;
    .end annotation
.end method

.method public abstract updateUser(Ljava/lang/String;Lcom/example/models/User;)Ljava/lang/Object;
    .annotation system Lretrofit2/http/PUT;
        value = "/api/v1/users/{user_id}"
    .end annotation

    .annotation system Lretrofit2/http/Path;
        value = "user_id"
    .end annotation

    .annotation system Lretrofit2/http/Body;
    .end annotation
.end method

.method public abstract deleteUser(Ljava/lang/String;)Ljava/lang/Object;
    .annotation system Lretrofit2/http/DELETE;
        value = "/api/v1/users/{user_id}"
    .end annotation

    .annotation system Lretrofit2/http/Path;
        value = "user_id"
    .end annotation
.end method

.method public abstract searchUsers(Ljava/lang/String;Ljava/lang/Integer;)Ljava/lang/Object;
    .annotation system Lretrofit2/http/GET;
        value = "/api/v1/users/search"
    .end annotation

    .annotation system Lretrofit2/http/Query;
        value = "q"
    .end annotation

    .annotation system Lretrofit2/http/Query;
        value = "page"
    .end annotation

    .annotation system Lretrofit2/http/Header;
        value = "Authorization"
    .end annotation
.end method
