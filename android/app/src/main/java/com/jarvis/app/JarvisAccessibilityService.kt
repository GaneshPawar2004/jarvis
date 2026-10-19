package com.jarvis.app

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.annotation.SuppressLint
import android.graphics.Color
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import kotlin.math.abs
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** JARVIS's eyes and hands on the phone: reads what's on screen as numbered elements and
 *  taps, types and scrolls. It only acts when cloud JARVIS asks it to (on the user's request). */
class JarvisAccessibilityService : AccessibilityService() {

    data class Element(val label: String, val kind: String, val bounds: Rect, val node: AccessibilityNodeInfo)

    private val elements = mutableMapOf<Int, Element>()
    private val main = Handler(Looper.getMainLooper())
    private var bubble: View? = null
    private var bubbleParams: WindowManager.LayoutParams? = null
    private var busy = 0
    private var appOpen = false

    override fun onServiceConnected() {
        instance = this
        appOpen = CloudLink.appVisible // JARVIS may already be on screen (e.g. right after an update)
        if (Prefs.floatingMic(this)) showBubble()
        onConnected?.let { main.post(it) }
    }

    override fun onDestroy() {
        removeBubble()
        instance = null
        super.onDestroy()
    }

    // ---------------- floating mic ----------------

    /** A draggable 🎤 on top of every app. Tap it to talk to JARVIS without leaving the app. */
    @SuppressLint("ClickableViewAccessibility")
    fun showBubble() = main.post {
        if (bubble != null) return@post
        val density = resources.displayMetrics.density
        val size = (54 * density).toInt()
        val view = TextView(this).apply {
            text = "🎤"
            textSize = 22f
            gravity = Gravity.CENTER
            alpha = 0.95f
            elevation = 6 * density
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.parseColor("#1565D8"))
                setStroke((2 * density).toInt(), Color.WHITE)
            }
        }
        val metrics = resources.displayMetrics
        val params = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = metrics.widthPixels - size - (6 * density).toInt()
            y = (metrics.heightPixels * 0.42f).toInt()
        }
        var startX = 0; var startY = 0; var touchX = 0f; var touchY = 0f; var dragged = false
        view.setOnTouchListener { v, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    startX = params.x; startY = params.y; touchX = event.rawX; touchY = event.rawY; dragged = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - touchX; val dy = event.rawY - touchY
                    if (abs(dx) > 12 * density || abs(dy) > 12 * density) dragged = true
                    if (dragged) {
                        params.x = (startX + dx).toInt(); params.y = (startY + dy).toInt()
                        windowManager().updateViewLayout(v, params)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    if (dragged) { // snap to the nearest side
                        params.x = if (params.x + size / 2 < metrics.widthPixels / 2) (6 * density).toInt()
                        else metrics.widthPixels - size - (6 * density).toInt()
                        windowManager().updateViewLayout(v, params)
                    } else {
                        ListenActivity.open(this)
                    }
                }
            }
            true
        }
        windowManager().addView(view, params)
        bubble = view
        bubbleParams = params
        refreshBubble()
    }

    fun removeBubble() = main.post {
        bubble?.let { windowManager().removeView(it) }
        bubble = null
    }

    /** Hide the bubble while JARVIS is tapping/typing, so it never covers what it's touching. */
    fun working(active: Boolean) = main.post {
        busy = (busy + if (active) 1 else -1).coerceAtLeast(0)
        refreshBubble()
    }

    /** No floating mic on top of the JARVIS app itself (it has its own mic button). */
    fun appInFront(open: Boolean) = main.post {
        appOpen = open
        refreshBubble()
    }

    private fun refreshBubble() {
        bubble?.visibility = if (busy > 0 || appOpen) View.GONE else View.VISIBLE
    }

    private fun windowManager() = getSystemService(WindowManager::class.java)

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}

    override fun onInterrupt() {}

    fun currentApp(): String = rootInActiveWindow?.packageName?.toString() ?: "unknown"

    /** Numbered list of buttons, text and input fields currently on screen. */
    fun readScreen(): List<String> {
        val root = rootInActiveWindow ?: throw IllegalStateException("Can't read this screen (it may be protected).")
        elements.clear()
        val lines = mutableListOf<String>()
        val covered = mutableSetOf<AccessibilityNodeInfo>()
        fun visit(node: AccessibilityNodeInfo) {
            if (!node.isVisibleToUser) return
            val bounds = Rect().also { node.getBoundsInScreen(it) }
            val editable = node.isEditable
            val clickable = node.isClickable || node.isLongClickable
            if (!bounds.isEmpty && node !in covered && elements.size < 120) {
                val label = when {
                    editable -> listOfNotNull(node.hintText, node.contentDescription, node.text, idName(node))
                        .map { it.toString().trim() }.firstOrNull { it.isNotEmpty() } ?: "input"
                    clickable -> labelOf(node)
                    else -> (node.text ?: node.contentDescription)?.toString()?.trim().orEmpty()
                }
                if (label.isNotEmpty() || editable) {
                    val kind = if (editable) "input" else if (clickable) "button" else "text"
                    val number = elements.size + 1
                    elements[number] = Element(label, kind, bounds, node)
                    var line = "$number. [$kind] ${label.take(80)}"
                    if (node.isPassword) line += " (password field)"
                    else if (editable && !node.text.isNullOrBlank() && node.text.toString() != label) line += " = \"${node.text.toString().take(60)}\""
                    lines += line
                    if (clickable) markChildren(node, covered)
                }
            }
            for (i in 0 until node.childCount) node.getChild(i)?.let { visit(it) }
        }
        visit(root)
        return lines.ifEmpty { listOf("(nothing readable on screen)") }
    }

    private fun idName(node: AccessibilityNodeInfo) = node.viewIdResourceName?.substringAfterLast('/')?.replace('_', ' ')

    private fun labelOf(node: AccessibilityNodeInfo): String {
        (node.text ?: node.contentDescription)?.toString()?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            labelOf(child).takeIf { it.isNotEmpty() }?.let { return it }
        }
        return idName(node).orEmpty()
    }

    private fun markChildren(node: AccessibilityNodeInfo, covered: MutableSet<AccessibilityNodeInfo>) {
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            if (!child.isEditable) {
                covered += child
                markChildren(child, covered)
            }
        }
    }

    fun element(number: Int): Element =
        elements[number] ?: throw IllegalArgumentException("Element $number is unknown. Read the screen first.")

    fun tap(number: Int) {
        val element = element(number)
        var node: AccessibilityNodeInfo? = element.node
        while (node != null && !node.isClickable) node = node.parent
        if (node == null || !node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            gesture(element.bounds.exactCenterX(), element.bounds.exactCenterY(), element.bounds.exactCenterX(), element.bounds.exactCenterY(), 60)
        }
        Thread.sleep(700)
    }

    /** Types into a field (any language). number 0 = the field that currently has focus. */
    fun type(text: String, number: Int) {
        val node = if (number > 0) element(number).node.also { it.performAction(AccessibilityNodeInfo.ACTION_CLICK) }
        else rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        node ?: throw IllegalStateException("No text field is selected. Give the field's number.")
        if (!node.isEditable) throw IllegalStateException("That element isn't a text field.")
        node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text) }
        if (!node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) throw IllegalStateException("The app refused the text.")
        Thread.sleep(300)
    }

    fun pressEnter(): Boolean {
        val focused = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT) ?: return false
        return focused.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
    }

    fun scroll(direction: String) {
        val forward = direction == "down" || direction == "right"
        val scrollable = findScrollable(rootInActiveWindow)
        val action = if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        if (scrollable?.performAction(action) == true) {
            Thread.sleep(600)
            return
        }
        val metrics = resources.displayMetrics
        val w = metrics.widthPixels.toFloat()
        val h = metrics.heightPixels.toFloat()
        when (direction) {
            "down" -> gesture(w / 2, h * 0.75f, w / 2, h * 0.25f, 350)
            "up" -> gesture(w / 2, h * 0.25f, w / 2, h * 0.75f, 350)
            "left" -> gesture(w * 0.8f, h / 2, w * 0.2f, h / 2, 350)
            else -> gesture(w * 0.2f, h / 2, w * 0.8f, h / 2, 350)
        }
        Thread.sleep(600)
    }

    private fun findScrollable(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
        node ?: return null
        if (node.isScrollable && node.isVisibleToUser) return node
        for (i in 0 until node.childCount) findScrollable(node.getChild(i))?.let { return it }
        return null
    }

    private fun gesture(x1: Float, y1: Float, x2: Float, y2: Float, durationMs: Long) {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val done = CountDownLatch(1)
        dispatchGesture(
            GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, durationMs)).build(),
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) = done.countDown()
                override fun onCancelled(gestureDescription: GestureDescription?) = done.countDown()
            },
            null
        )
        done.await(3, TimeUnit.SECONDS)
    }

    companion object {
        @Volatile var instance: JarvisAccessibilityService? = null
            private set

        /** Lets the open app refresh its "phone control" banner when the service starts. */
        var onConnected: (() -> Unit)? = null
    }
}
