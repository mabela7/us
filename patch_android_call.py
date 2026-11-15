#!/usr/bin/env python3
"""Run in the project root AFTER `npx cap add android` / `npx cap sync` and BEFORE gradle.
Adds a call-style (Answer / Decline, full-screen, ringing) notification for FCM data messages type=call.
Idempotent. Pure Python, no deps."""
import glob, os, re, sys

root = "android/app/src/main"
mans = f"{root}/AndroidManifest.xml"
mains = glob.glob(f"{root}/java/**/MainActivity.java", recursive=True)
if not mains or not os.path.exists(mans):
    sys.exit("android project not found - run after `npx cap add android`")
main = mains[0]
d = os.path.dirname(main)
pkg = re.search(r"package\s+([\w.]+);", open(main).read()).group(1)

SERVICE = """package PKG;

import android.app.*;
import android.content.*;
import android.media.*;
import android.net.Uri;
import android.os.Build;
import androidx.core.app.NotificationCompat;
import android.graphics.Color;
import android.text.SpannableString;
import android.text.style.ForegroundColorSpan;
import com.google.firebase.messaging.RemoteMessage;
import java.util.Map;

public class CallMessagingService extends com.capacitorjs.plugins.pushnotifications.MessagingService {
  static final String CH = "calls_ring";
  static final int NID = 7001;

  @Override
  public void onMessageReceived(RemoteMessage m) {
    Map<String, String> d = m.getData();
    if ("call".equals(d.get("type")) && m.getNotification() == null) {
      if (!MainActivity.fg) ring(d);   // app open -> the in-app call screen handles it
      return;
    }
    if ("callend".equals(d.get("type"))) { cancel(this); return; }
    super.onMessageReceived(m);
  }

  static void cancel(Context c) {
    ((NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE)).cancel(NID);
  }

  PendingIntent pi(String act, String from, int rc) {
    Intent i = new Intent(this, MainActivity.class).setAction("CALL_" + act)
        .putExtra("callAct", act).putExtra("callFrom", from)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
    return PendingIntent.getActivity(this, rc, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
  }

  void ring(Map<String, String> d) {
    NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
    Uri snd = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
    if (Build.VERSION.SDK_INT >= 26) {
      AudioAttributes aa = new AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
          .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
      NotificationChannel ch = new NotificationChannel(CH, "Incoming calls", NotificationManager.IMPORTANCE_HIGH);
      ch.setSound(snd, aa);
      ch.enableVibration(true);
      ch.setVibrationPattern(new long[]{0, 800, 600, 800, 600, 800});
      ch.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
      nm.createNotificationChannel(ch);
    }
    String from = d.get("fromUid") == null ? "" : d.get("fromUid");
    String name = d.get("name") == null ? "Someone" : d.get("name");
    boolean vid = "1".equals(d.get("video"));
    PendingIntent open = pi("open", from, 1), answer = pi("answer", from, 2), decline = pi("decline", from, 3);
    SpannableString ans = new SpannableString("Answer");
    ans.setSpan(new ForegroundColorSpan(Color.parseColor("#2ecc71")), 0, ans.length(), 0);
    SpannableString dec = new SpannableString("Decline");
    dec.setSpan(new ForegroundColorSpan(Color.parseColor("#ff5a5f")), 0, dec.length(), 0);
    NotificationCompat.Builder b = new NotificationCompat.Builder(this, CH)
        .setSmallIcon(android.R.drawable.sym_action_call)
        .setContentTitle(name)
        .setContentText(vid ? "Incoming video call" : "Incoming voice call")
        .setPriority(NotificationCompat.PRIORITY_MAX)
        .setCategory(NotificationCompat.CATEGORY_CALL)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setOngoing(true)
        .setAutoCancel(false)
        .setTimeoutAfter(40000)
        .setContentIntent(open)
        .addAction(android.R.drawable.ic_menu_close_clear_cancel, dec, decline)
        .addAction(android.R.drawable.sym_action_call, ans, answer);
    if (Build.VERSION.SDK_INT < 26) { b.setSound(snd, AudioManager.STREAM_RING); b.setVibrate(new long[]{0, 800, 600, 800}); }
    Notification n = b.build();
    n.flags |= Notification.FLAG_INSISTENT;   // keep ringing until answered / declined / timeout
    nm.notify(NID, n);
  }
}
"""

MAIN = """package PKG;

import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Build;
import android.view.WindowManager;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

public class MainActivity extends BridgeActivity {
  static boolean fg = false;
  static String pending = "";

  @CapacitorPlugin(name = "NativeCall")
  public static class NativeCall extends Plugin {
    @PluginMethod
    public void take(PluginCall c) {
      JSObject r = new JSObject();
      r.put("v", pending);
      pending = "";
      c.resolve(r);
    }
    @PluginMethod
    public void download(PluginCall c) {
      try {
        String url = c.getString("url"), name = c.getString("name", "file"), mime = c.getString("mime", "");
        if (url == null || url.isEmpty()) { c.reject("no url"); return; }
        DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
        r.setTitle(name);
        r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        if (mime != null && !mime.isEmpty()) r.setMimeType(mime);
        r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
        ((DownloadManager) getContext().getSystemService(Context.DOWNLOAD_SERVICE)).enqueue(r);
        c.resolve();
      } catch (Exception e) {
        c.reject(String.valueOf(e.getMessage()));
      }
    }
    @PluginMethod
    public void cancel(PluginCall c) {
      CallMessagingService.cancel(getContext());
      c.resolve();
    }
  }

  @Override
  public void onCreate(Bundle s) {
    registerPlugin(NativeCall.class);
    super.onCreate(s);
    handle(getIntent());
  }

  @Override
  protected void onNewIntent(Intent i) {
    super.onNewIntent(i);
    setIntent(i);
    handle(i);
    try { getBridge().eval("window.dispatchEvent(new Event('nativecall'))", null); } catch (Exception e) {}
  }

  void handle(Intent i) {
    if (i == null) return;
    String a = i.getStringExtra("callAct");
    if (a == null) return;
    pending = a + ":" + i.getStringExtra("callFrom");
    i.removeExtra("callAct");
    CallMessagingService.cancel(this);
    if (Build.VERSION.SDK_INT >= 27) { setShowWhenLocked(true); setTurnScreenOn(true); }
    else getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
  }

  @Override public void onResume() { super.onResume(); fg = true; }
  @Override public void onPause() { fg = false; super.onPause(); }
}
"""

open(f"{d}/CallMessagingService.java", "w").write(SERVICE.replace("PKG", pkg))
open(main, "w").write(MAIN.replace("PKG", pkg))

m = open(mans).read()
if 'xmlns:tools' not in m:
    m = m.replace("<manifest ", '<manifest xmlns:tools="http://schemas.android.com/tools" ', 1)
for perm in ["USE_FULL_SCREEN_INTENT", "VIBRATE", "POST_NOTIFICATIONS", "WAKE_LOCK"]:
    tag = f'android.permission.{perm}'
    if tag not in m:
        m = m.replace("</manifest>", f'    <uses-permission android:name="{tag}" />\n</manifest>')
if "WRITE_EXTERNAL_STORAGE" not in m:
    m = m.replace("</manifest>", '    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="28" />\n</manifest>')
if "CallMessagingService" not in m:
    svc = f"""
        <service android:name="{pkg}.CallMessagingService" android:exported="false">
            <intent-filter><action android:name="com.google.firebase.MESSAGING_EVENT" /></intent-filter>
        </service>
        <service android:name="com.capacitorjs.plugins.pushnotifications.MessagingService" tools:node="remove" />
    """
    m = m.replace("</application>", svc + "</application>")
open(mans, "w").write(m)

# firebase-messaging is not on the app's compile classpath by default (the push plugin hides it)
g = "android/app/build.gradle"
gs = open(g).read()
if "firebase-bom" not in gs:
    gs, n = re.subn(r"^dependencies\s*\{", "dependencies {\n    implementation platform('com.google.firebase:firebase-bom:32.7.0')\n    implementation 'com.google.firebase:firebase-messaging'", gs, count=1, flags=re.M)
    if not n:
        sys.exit("dependencies block not found in app/build.gradle")
    open(g, "w").write(gs)
print("call-style notification patched, package", pkg)
    
