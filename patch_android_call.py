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
import androidx.core.app.Person;
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
    String from = d.get("from") == null ? "" : d.get("from");
    String name = d.get("name") == null ? "Someone" : d.get("name");
    boolean vid = "1".equals(d.get("video"));
    PendingIntent open = pi("open", from, 1), answer = pi("answer", from, 2), decline = pi("decline", from, 3);
    Person p = new Person.Builder().setName(name).setImportant(true).build();
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
        .setFullScreenIntent(open, true)
        .setStyle(NotificationCompat.CallStyle.forIncomingCall(p, decline, answer));
    if (Build.VERSION.SDK_INT < 26) { b.setSound(snd, AudioManager.STREAM_RING); b.setVibrate(new long[]{0, 800, 600, 800}); }
    Notification n = b.build();
    n.flags |= Notification.FLAG_INSISTENT;   // keep ringing until answered / declined / timeout
    nm.notify(NID, n);
  }
}
"""

MAIN = """package PKG;

import android.content.Intent;
import android.os.Bundle;
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

  @Override protected void onResume() { super.onResume(); fg = true; }
  @Override protected void onPause() { fg = false; super.onPause(); }
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
if "CallMessagingService" not in m:
    svc = f"""
        <service android:name="{pkg}.CallMessagingService" android:exported="false">
            <intent-filter><action android:name="com.google.firebase.MESSAGING_EVENT" /></intent-filter>
        </service>
        <service android:name="com.capacitorjs.plugins.pushnotifications.MessagingService" tools:node="remove" />
    """
    m = m.replace("</application>", svc + "</application>")
open(mans, "w").write(m)
print("call-style notification patched, package", pkg)
