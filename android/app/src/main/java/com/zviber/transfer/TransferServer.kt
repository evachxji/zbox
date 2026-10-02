package com.zviber.transfer

import fi.iki.elonen.NanoHTTPD
import fi.iki.elonen.NanoHTTPD.Response.Status
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString

/**
 * 接收方 HTTP 服务端：NanoHTTPD 监听 53327，路由 /api/localsend/v2 下五个端点。
 */
class TransferServer(private val receiver: Receiver) : NanoHTTPD(PROTOCOL_PORT) {

    override fun serve(session: IHTTPSession): Response {
        val uri = session.uri ?: ""
        if (!uri.startsWith(API_PREFIX)) {
            return error(Status.NOT_FOUND, "not found")
        }
        val route = uri.removePrefix(API_PREFIX)
        return try {
            when (session.method to route) {
                Method.POST to "/register" -> handleRegister(session)
                Method.GET to "/info" ->
                    jsonResponse(Status.OK, protoJson.encodeToString(Settings.localInfo()))
                Method.POST to "/prepare-upload" -> receiver.handlePrepare(session)
                Method.POST to "/upload" -> receiver.handleUpload(session)
                Method.POST to "/cancel" -> receiver.handleCancel(session)
                else -> error(Status.NOT_FOUND, "not found")
            }
        } catch (e: Exception) {
            error(Status.INTERNAL_ERROR, e.message ?: "internal error")
        }
    }

    /** POST /register：登记对端 + 回本机 info */
    private fun handleRegister(session: IHTTPSession): Response {
        val body = readJsonBody(session) ?: return error(Status.BAD_REQUEST, "invalid body")
        val info = try {
            protoJson.decodeFromString<DeviceInfo>(body)
        } catch (_: Exception) {
            return error(Status.BAD_REQUEST, "invalid json")
        }
        if (info.fingerprint != Settings.fingerprint) {
            DeviceStore.upsert(info, session.remoteIpAddress ?: "")
        }
        return jsonResponse(Status.OK, protoJson.encodeToString(Settings.localInfo()))
    }

    companion object {
        /** 422 状态（NanoHTTPD 枚举不含，自定义实现） */
        val STATUS_422: NanoHTTPD.Response.IStatus = object : NanoHTTPD.Response.IStatus {
            override fun getDescription(): String = "422 Unprocessable Entity"
            override fun getRequestStatus(): Int = 422
        }

        /** 读取 JSON 请求体（application/json 会落入 postData） */
        fun readJsonBody(session: IHTTPSession): String? {
            return try {
                val map = HashMap<String, String>()
                session.parseBody(map)
                map["postData"]
            } catch (_: Exception) {
                null
            }
        }

        fun jsonResponse(status: NanoHTTPD.Response.IStatus, body: String): Response =
            NanoHTTPD.newFixedLengthResponse(status, "application/json", body)

        fun error(status: NanoHTTPD.Response.IStatus, message: String): Response =
            jsonResponse(status, protoJson.encodeToString(ErrorMessage(message)))
    }
}

/** 错误应答体（message 走 JSON 编码，避免裸插值破坏格式） */
@Serializable
private data class ErrorMessage(val message: String)