package com.boloupay.bolo_upay

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.telephony.PhoneStateListener
import android.telephony.TelephonyCallback
import android.telephony.TelephonyManager
import androidx.activity.result.contract.ActivityResultContracts
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

/**
 * R11 call detection: tells Flutter whether the phone is in a call, and nothing else.
 *
 * In a call = the telephony state is off-hook (a GSM call), or the audio mode is a
 * call mode: WhatsApp, IMO and Messenger calls set MODE_IN_COMMUNICATION, which
 * the telephony state never sees. Numbers and audio are never read: the number
 * Android passes to the old listener is ignored, and only a yes/no crosses the channel.
 *
 * Methods on "bolo/call_state"; live yes/no on "bolo/call_state/events" (an
 * EventChannel on the same name would replace the method handler: one handler per name).
 * Stays a FlutterFragmentActivity: local_auth and biometric_signature need it.
 */
class MainActivity : FlutterFragmentActivity() {
    private val telephony by lazy { getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager }
    private val audio by lazy { getSystemService(Context.AUDIO_SERVICE) as AudioManager }
    private val main = Handler(Looper.getMainLooper())
    private var offHook = false
    private var listener: Any? = null // TelephonyCallback (API 31+) or PhoneStateListener
    private var sink: EventChannel.EventSink? = null
    private var last: Boolean? = null
    private var pending: MethodChannel.Result? = null

    // registered before the activity starts, as the Activity Result API requires
    private val askPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) startTelephony()
        pending?.success(ok)
        pending = null
    }

    // no audio-mode callback before API 31: a cheap poll, only while Flutter listens
    private val poll = object : Runnable {
        override fun run() {
            emit()
            main.postDelayed(this, 2000)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        MethodChannel(messenger, "bolo/call_state").setMethodCallHandler { call, result ->
            when (call.method) {
                "permission" -> result.success(granted())
                "requestPermission" -> when {
                    granted() -> { startTelephony(); result.success(true) }
                    pending != null -> result.error("busy", "a permission request is already open", null)
                    else -> { pending = result; askPermission.launch(Manifest.permission.READ_PHONE_STATE) }
                }
                "inCall" -> result.success(if (granted()) inCall() else null)
                "speakerOn" -> result.success(speakerOn())
                else -> result.notImplemented()
            }
        }
        EventChannel(messenger, "bolo/call_state/events").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
                sink = events
                last = null
                startTelephony()
                main.removeCallbacks(poll)
                poll.run()
            }

            override fun onCancel(arguments: Any?) {
                sink = null
                main.removeCallbacks(poll)
            }
        })
    }

    private fun granted() = checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED

    private fun inCall(): Boolean {
        val mode = audio.mode
        return offHook || mode == AudioManager.MODE_IN_CALL || mode == AudioManager.MODE_IN_COMMUNICATION
    }

    /** Call audio on the loudspeaker (R10 speaker_echo: a scammer coaching the victim on speaker). */
    @Suppress("DEPRECATION")
    private fun speakerOn(): Boolean {
        if (audio.isSpeakerphoneOn) return true
        return Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            audio.communicationDevice?.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
    }

    private fun onState(state: Int) {
        offHook = state == TelephonyManager.CALL_STATE_OFFHOOK
        emit()
    }

    private fun emit() {
        if (sink == null || !granted()) return
        val now = inCall()
        if (now != last) {
            last = now
            sink?.success(now)
        }
    }

    /** Follows the telephony call state; both APIs report the current state right away. */
    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    private fun startTelephony() {
        if (listener != null || !granted()) return
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val cb = object : TelephonyCallback(), TelephonyCallback.CallStateListener {
                    override fun onCallStateChanged(state: Int) = onState(state)
                }
                telephony.registerTelephonyCallback(mainExecutor, cb)
                listener = cb
            } else {
                val l = object : PhoneStateListener() {
                    override fun onCallStateChanged(state: Int, phoneNumber: String?) = onState(state) // number ignored
                }
                telephony.listen(l, PhoneStateListener.LISTEN_CALL_STATE)
                listener = l
            }
        } catch (_: SecurityException) {
            listener = null // revoked between the check and the call: the next request retries
        }
    }

    @Suppress("DEPRECATION")
    override fun onDestroy() {
        main.removeCallbacks(poll)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (listener as? TelephonyCallback)?.let { telephony.unregisterTelephonyCallback(it) }
        } else {
            (listener as? PhoneStateListener)?.let { telephony.listen(it, PhoneStateListener.LISTEN_NONE) }
        }
        listener = null
        super.onDestroy()
    }
}
